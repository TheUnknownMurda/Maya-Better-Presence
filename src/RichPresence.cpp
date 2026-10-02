#include "RichPresence.h"

#include <maya/MGlobal.h>
#include <maya/MFileIO.h>
#include <maya/MEventMessage.h>
#include <maya/MSceneMessage.h>
#include <maya/MStringArray.h>
#include <maya/MItDependencyNodes.h>
#include <maya/MFnMesh.h>
#include <sstream>
#include <chrono>

#include <filesystem>
#include <algorithm>
#include "ini.h"

#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif


namespace
{
	std::string lastUpdateError;

	bool IsContinuationByte(char c)
	{
		return (static_cast<unsigned char>(c) & 0xC0) == 0x80;
	}

	// Discord expects UTF-8 and rejects the whole activity if a text is too short or too long
	// (2 characters to 128 bytes for most fields), so too short texts are dropped and too long ones are truncated.
	std::optional<std::string> ToDiscordText(const MString& text, size_t minCharacters = 2, size_t maxBytes = 128)
	{
		const std::string ellipsis = "\xE2\x80\xA6";

		std::string utf8 = text.asUTF8();
		size_t characters = 0;
		for (char c : utf8)
		{
			if (!IsContinuationByte(c))
				++characters;
		}
		if (characters < minCharacters)
			return std::nullopt;

		if (utf8.size() > maxBytes)
		{
			size_t cut = maxBytes - ellipsis.size();
			while (cut > 0 && IsContinuationByte(utf8[cut]))
				--cut; // never split a multi-byte character
			utf8 = utf8.substr(0, cut) + ellipsis;
		}
		return utf8;
	}

	// A truncated link would be broken, so an invalid one is left out instead
	bool IsValidButtonUrl(const std::string& url)
	{
		bool web = url.rfind("https://", 0) == 0 || url.rfind("http://", 0) == 0;
		return web && url.size() <= 512 && url.find(' ') == std::string::npos;
	}

	const MString SEPARATOR(L" \u00B7 ");
}


RichPresence::RichPresence()
{
	Initialize();
}

RichPresence::~RichPresence()
{
	BlockUpdates();
	Disable();
	MMessage::removeCallback(runCallbacksTimerId);
	// Remove the status right away instead of waiting for Discord to notice the disconnection
	client->ClearRichPresence();
	client.reset();
	// The SDK releases the callbacks of updates still waiting for Discord on the next RunCallbacks.
	// That release runs code from this plug-in, so it must happen now: once the plug-in is unloaded,
	// the next RunCallbacks (from a reloaded plug-in, or at exit) would crash Maya.
	discordpp::RunCallbacks();
}

void RichPresence::Enable()
{
	BlockUpdates();

	// config.ini is found from where the plug-in was loaded (plug-ins/<version> inside the module)
	// rather than through Maya's module list, which the installer can't update during a session
	// when the user's folder has an accent
	std::filesystem::path path(pluginDirectory.asWChar());
	if (!path.has_filename())
		path = path.parent_path();
	path = path.parent_path().parent_path() / L"config" / L"config.ini";

	mINI::INIFile file(path);
	mINI::INIStructure ini;
	file.read(ini);

	mINI::INIMap<std::string> section = ini.get("General");
	// The scene and project are always followed, since custom text can show them even when
	// the automatic text doesn't. The options only decide what the automatic text shows.
	RegisterSceneCallbacks();
	RegisterProjectCallback();
	displayScene = (section.get("details") == "true");
	displayProject = (section.get("state") == "true");
	customTextWhileIdle = (section.get("custom_text_while_idle") == "true");
	OnFileChange(nullptr); // we run it once manually to force a refresh
	OnProjectChange(nullptr);


	bool reset_time_with_scene = (section.get("reset_time_with_scene") == "true");
	SetResetTimeOnChange(reset_time_with_scene);

	// Settings from before this option existed don't have it, and it is on by default
	SetDisplayTask(!section.has("task") || section.get("task") == "true");

	// "Autodesk Maya 2027.2", shown when hovering the Maya logo
	MString installedVersion;
	MStringArray words;
	MGlobal::executeCommand("about -installedVersion", installedVersion);
	installedVersion.split(' ', words);
	mayaVersion = MString("Autodesk Maya");
	if (words.length() > 0)
		mayaVersion += MString(" ") + words[words.length() - 1];

	// The task and renderer are read by a Python script so the wording can be changed without recompiling
	contextScriptAvailable = MGlobal::executePythonCommand("import RichPresenceUI.context") == MS::kSuccess;
	lastUserActivity = Clock::now();
	PollMayaState();

	RefreshTimestamp(); // one forced refresh to add the timestamp to activity
	UnblockUpdates();
	// The first update is sent by initializePlugin once the text settings are applied too,
	// otherwise Discord would show the automatic text for a few seconds at every start
}

void RichPresence::Disable()
{
	RemoveSceneCallbacks();
	RemoveProjectCallback();
}

void RichPresence::Initialize()
{
	client = std::make_unique<discordpp::Client>();
	client->SetApplicationId(APPLICATION_ID);
	// The SDK only delivers its results when RunCallbacks is called regularly
	runCallbacksTimerId = MTimerMessage::addTimerCallback(0.5f, OnTimer);
}

void RichPresence::Update()
{
	if (updatesBlocked)
		return;
	BuildActivity();
	updatePending = true;
	FlushUpdate();
}

void RichPresence::BuildActivity()
{
	// Built from scratch every time, since a button can be added to an activity but not removed
	discordpp::Activity built;
	built.SetType(discordpp::ActivityTypes::Playing);
	built.SetDetails(ToDiscordText(dDetails));
	built.SetState(ToDiscordText(dState));
	// The timer pauses while idle
	if (!idle)
		built.SetTimestamps(dTimestamp);

	discordpp::ActivityAssets assets;
	assets.SetLargeImage(LARGE_IMAGE);
	MString largeText = mayaVersion;
	if (rendererName.length())
		largeText += SEPARATOR + rendererName;
	assets.SetLargeText(ToDiscordText(largeText));
	built.SetAssets(assets);

	std::optional<std::string> label = ToDiscordText(buttonLabel, 1, 32);
	std::string url = buttonUrl.asUTF8();
	if (label && IsValidButtonUrl(url))
	{
		discordpp::ActivityButton button;
		button.SetLabel(*label);
		button.SetUrl(url);
		built.AddButton(button);
	}

	activity = built;
}

// Only one update is sent at a time and the SDK holds it until Discord is running,
// so changes made while Discord is closed collapse into the latest activity instead of piling up.
void RichPresence::FlushUpdate()
{
	if (!updatePending || updateInFlight || Clock::now() < nextUpdateAllowed)
		return;
	updatePending = false;
	if (IsHidden())
	{
		if (!presenceCleared)
		{
			client->ClearRichPresence();
			presenceCleared = true;
			lastSentActivity.reset(); // nothing to refresh while hidden
			nextUpdateAllowed = Clock::now() + UPDATE_INTERVAL;
		}
		return;
	}
	if (lastSentActivity && activity.Equals(*lastSentActivity))
		return;
	SendUpdate();
}

void RichPresence::SendUpdate()
{
	presenceCleared = false;
	lastSentActivity = activity;
	updateInFlight = true;
	lastUpdateSent = Clock::now();
	nextUpdateAllowed = lastUpdateSent + UPDATE_INTERVAL;
	client->UpdateRichPresence(activity, OnUpdateResult);
}

void RichPresence::OnTimer(float elapsedTime, float lastTime, void* clientData)
{
	discordpp::RunCallbacks();
	if (!instance)
		return;

	if (Clock::now() >= instance->nextPoll)
	{
		instance->nextPoll = Clock::now() + POLL_INTERVAL;
		instance->PollMayaState();
	}

	if (!instance->updateInFlight && instance->lastSentActivity
		&& Clock::now() - instance->lastUpdateSent >= REFRESH_INTERVAL)
	{
		instance->lastSentActivity.reset();
		instance->updatePending = true;
	}
	instance->FlushUpdate();
}

void RichPresence::PollMayaState()
{
	if (UserInputInMaya())
		RegisterUserActivity();
	else
		CheckIdle();

	int modified = 0;
	MGlobal::executeCommand("file -q -modified", modified);
	MString newTask;
	MString newRenderer;
	if (contextScriptAvailable)
	{
		if (displayTask || TemplatesUse("{task}"))
			MGlobal::executePythonCommand("__import__('RichPresenceUI.context', fromlist=['']).current_task()", newTask);
		MGlobal::executePythonCommand("__import__('RichPresenceUI.context', fromlist=['']).current_renderer()", newRenderer);
	}

	bool statsChanged = false;
	if (NeedsSceneStats() && Clock::now() >= nextStatsPoll)
	{
		Clock::time_point start = Clock::now();
		statsChanged = RefreshSceneStats();
		// On very heavy scenes the statistics are read less often, so they never take more than 0.1% of the time
		nextStatsPoll = Clock::now() + std::max<Clock::duration>(STATS_INTERVAL, (Clock::now() - start) * 1000);
	}

	if ((modified != 0) == sceneModified && newTask == task && newRenderer == rendererName && !statsChanged)
		return;
	sceneModified = modified != 0;
	task = newTask;
	rendererName = newRenderer;
	RefreshDetails();
	RefreshState();
	Update();
}

bool RichPresence::NeedsSceneStats() const
{
	bool automaticStats = displayProject && !projectName.length() && !UsesCustomText(customState);
	return automaticStats || TemplatesUse("{stats}");
}

bool RichPresence::RefreshSceneStats()
{
	// Counted here rather than in Python, which took 60 ms on a scene of 20,000 meshes.
	// The counts are stored by Maya, nothing gets evaluated.
	unsigned int meshes = 0;
	unsigned long long polygons = 0;
	for (MItDependencyNodes nodes(MFn::kMesh); !nodes.isDone(); nodes.next())
	{
		MStatus status;
		MFnMesh mesh(nodes.thisNode(), &status);
		// Intermediate meshes are hidden construction history, not objects of the scene
		if (!status || mesh.isIntermediateObject())
			continue;
		++meshes;
		int count = mesh.numPolygons(&status);
		if (status)
			polygons += count;
	}

	// The wording comes from Python so it can be changed without recompiling
	MString stats;
	if (contextScriptAvailable)
	{
		std::string command = "__import__('RichPresenceUI.context', fromlist=['']).format_statistics("
			+ std::to_string(meshes) + ", " + std::to_string(polygons) + ")";
		MGlobal::executePythonCommand(command.c_str(), stats);
	}
	if (stats == sceneStats)
		return false;
	sceneStats = stats;
	return true;
}

// True when the keyboard or mouse was used since the last check while Maya was the active application,
// so typing in a web browser doesn't count as working in Maya.
bool RichPresence::UserInputInMaya()
{
#ifdef _WIN32
	LASTINPUTINFO info{ sizeof(LASTINPUTINFO), 0 };
	if (!GetLastInputInfo(&info))
		return true; // without this information the user is never considered idle
	bool newInput = info.dwTime != lastInputTick;
	lastInputTick = info.dwTime;

	DWORD foregroundProcess = 0;
	GetWindowThreadProcessId(GetForegroundWindow(), &foregroundProcess);
	return newInput && foregroundProcess == GetCurrentProcessId();
#else
	return true;
#endif
}

void RichPresence::RegisterUserActivity()
{
	if (idle)
		LeaveIdle();
	lastUserActivity = Clock::now();
}

void RichPresence::CheckIdle()
{
	bool shouldBeIdle = idleAction != IdleAction::Off
		&& Clock::now() - lastUserActivity >= std::chrono::minutes(idleMinutes);
	if (shouldBeIdle && !idle)
	{
		idle = true;
		RefreshDetails();
		RefreshState();
		Update();
	}
	else if (!shouldBeIdle && idle)
	{
		LeaveIdle(); // the idle option was turned off or its delay increased
	}
}

void RichPresence::LeaveIdle()
{
	// The time away doesn't count, so the timer resumes where it paused
	Clock::time_point now = Clock::now();
	uint64_t away = std::chrono::duration_cast<std::chrono::seconds>(now - lastUserActivity).count();
	uint64_t nowSeconds = static_cast<uint64_t>(time(nullptr));
	dTimestamp.SetStart(std::min(dTimestamp.Start() + away, nowSeconds));
	lastUserActivity = now;
	idle = false;
	RefreshDetails();
	RefreshState();
	Update();
}

void RichPresence::OnUpdateResult(const discordpp::ClientResult& result)
{
	if (!instance || result.Type() == discordpp::ErrorType::ClientDestroyed)
		return;
	instance->updateInFlight = false;
	if (result.Successful())
	{
		lastUpdateError.clear();
		return;
	}
	// An invalid activity would fail again, anything else is retried a bit later
	if (result.Type() != discordpp::ErrorType::ValidationError)
	{
		instance->lastSentActivity.reset();
		instance->updatePending = true;
		instance->nextUpdateAllowed = Clock::now() + RETRY_INTERVAL;
	}

	// Only report an error once instead of on every update
	std::string error = result.Error();
	if (error == lastUpdateError)
		return;
	lastUpdateError = error;

	MString message;
	message.setUTF8(("Discord Rich Presence: " + error).c_str());
	MGlobal::displayWarning(message);
}

void RichPresence::SetDetails(MString details)
{
	dDetails = details;
}

void RichPresence::SetState(MString state)
{
	dState = state;
}

void RichPresence::RefreshTimestamp()
{
	dTimestamp.SetStart(time(nullptr));
}

void RichPresence::RegisterSceneCallbacks()
{
	if (sceneCallbackIds.size() != 0)
	{
#ifdef DEBUG
		MGlobal::displayInfo("Scene callbacks are already registered.");
#endif // DEBUG
		return;
	}
	sceneCallbackIds.push_back(MSceneMessage::addCallback(MSceneMessage::kAfterNew, OnFileChange));
	sceneCallbackIds.push_back(MSceneMessage::addCallback(MSceneMessage::kAfterOpen, OnFileChange));
	sceneCallbackIds.push_back(MSceneMessage::addCallback(MSceneMessage::kAfterSave, OnFileSave));
}

void RichPresence::RemoveSceneCallbacks()
{
	if (sceneCallbackIds.size() == 0)
	{
#ifdef DEBUG
		MGlobal::displayInfo("Scene callbacks are not registered.");
#endif
		return;
	}
	for (auto& id : sceneCallbackIds)
	{
		MSceneMessage::removeCallback(id);
	}
	sceneCallbackIds.clear();
}

void RichPresence::RegisterProjectCallback()
{
	if (projectChangeCallbackId != -1)
	{
#ifdef DEBUG
		MGlobal::displayInfo("Project change callback is already registered.");
#endif // DEBUG
		return;
	}
	projectChangeCallbackId = MEventMessage::addEventCallback("workspaceChanged", OnProjectChange);
}

void RichPresence::RemoveProjectCallback()
{
	if (projectChangeCallbackId == -1)
	{
#ifdef DEBUG
		MGlobal::displayInfo("Project change callback is not registered.");
#endif // DEBUG
		return;
	}
	MStatus status = MEventMessage::removeCallback(projectChangeCallbackId);
	projectChangeCallbackId = -1;
}

void RichPresence::OnProjectChange(void* clientData)
{
	MString root;
	MGlobal::executeCommand("workspace -q -rootDirectory", root);
	MString defaultRoot;
	MGlobal::executeCommand("internalVar -userWorkspaceDir", defaultRoot);
	defaultRoot += "default/";

	// Maya's own default project, simply named "default", says nothing about the work
	if (MString(root).toLowerCase() == defaultRoot.toLowerCase())
	{
		instance->projectName.clear();
		instance->RefreshSceneStats();
	}
	else
	{
		// Wide strings keep accented names intact, and filename() unlike stem() keeps names with dots whole
		std::filesystem::path path(root.asWChar());
		if (!path.has_filename())
			path = path.parent_path();
		instance->projectName = MString(path.filename().wstring().c_str());
	}

	instance->RefreshDetails();
	instance->RefreshState();
	instance->Update();
}

// The second line shows the project, or scene statistics when Maya's default project is used
void RichPresence::RefreshState()
{
	if (UsesCustomText(customState))
		SetState(ExpandTemplate(customState));
	else if (!displayProject)
		SetState("");
	else if (projectName.length())
		SetState(projectName);
	else
		SetState(sceneStats);
}

void RichPresence::OnFileChange(void* clientData)
{
	instance->sceneModified = false;
	instance->UpdateSceneName();
	if (instance->NeedsSceneStats())
		instance->RefreshSceneStats();
	instance->RefreshState();
	if (instance->resetTimeOnChange)
		instance->RefreshTimestamp();

	instance->Update();
}

void RichPresence::OnFileSave(void* clientData)
{
	// A "Save As" can rename the scene, but saving should never reset the timer
	MString previousDetails = instance->dDetails;
	MString previousState = instance->dState;
	instance->sceneModified = false;
	instance->UpdateSceneName();
	instance->RefreshState();
	if (instance->dDetails != previousDetails || instance->dState != previousState)
		instance->Update();
}

void RichPresence::UpdateSceneName()
{
	std::filesystem::path path(MFileIO::currentFile().asWChar());
	sceneName = MString(path.filename().wstring().c_str());
	RefreshDetails();
}

// The first line shows what the user is doing and on which scene, like "Modeling - hero.ma*" (with a middle dot)
// where the * marks unsaved changes, as in Maya's title bar. "Idle" takes the place of the task.
void RichPresence::RefreshDetails()
{
	if (UsesCustomText(customDetails))
	{
		SetDetails(ExpandTemplate(customDetails));
		return;
	}

	MString scene = displayScene ? SceneText() : MString();
	MString shownTask = idle ? MString("Idle") : (displayTask ? task : MString());

	if (shownTask.length() && scene.length())
		SetDetails(shownTask + SEPARATOR + scene);
	else if (shownTask.length())
		SetDetails(shownTask);
	else if (scene.length())
		SetDetails(MString("Working on: ") + scene);
	else
		SetDetails("");
}

void RichPresence::SetResetTimeOnChange(bool reset)
{
	resetTimeOnChange = reset;
}

MString RichPresence::SceneText() const
{
	// The * marks unsaved changes, as in Maya's title bar
	return sceneName.length() ? sceneName + (sceneModified ? "*" : "") : MString();
}

bool RichPresence::TemplatesUse(const MString& placeholder) const
{
	return customDetails.indexW(placeholder) >= 0 || customState.indexW(placeholder) >= 0;
}

MString RichPresence::ExpandTemplate(const MString& text) const
{
	MString expanded = text;
	expanded.substitute("{task}", idle ? MString("Idle") : task);
	expanded.substitute("{scene}", SceneText());
	expanded.substitute("{project}", projectName);
	expanded.substitute("{stats}", sceneStats);

	// A placeholder with nothing to show could leave spaces at either end
	std::wstring trimmed = expanded.asWChar();
	size_t first = trimmed.find_first_not_of(L" \t");
	size_t last = trimmed.find_last_not_of(L" \t");
	trimmed = first == std::wstring::npos ? L"" : trimmed.substr(first, last - first + 1);
	return MString(trimmed.c_str());
}

void RichPresence::SetDisplayTask(bool display)
{
	displayTask = display;
	if (!displayTask && !TemplatesUse("{task}"))
		task.clear();
	RefreshDetails();
	RefreshState();
}

void RichPresence::SetDisplayScene(bool display)
{
	displayScene = display;
	RefreshDetails();
}

void RichPresence::SetDisplayProject(bool display)
{
	displayProject = display;
	if (NeedsSceneStats())
		RefreshSceneStats();
	RefreshState();
}

void RichPresence::SetCustomDetails(MString text)
{
	customDetails = text;
	if (NeedsSceneStats())
		RefreshSceneStats();
	RefreshDetails();
}

void RichPresence::SetCustomState(MString text)
{
	customState = text;
	if (NeedsSceneStats())
		RefreshSceneStats();
	RefreshState();
}

void RichPresence::SetCustomTextWhileIdle(bool keep)
{
	customTextWhileIdle = keep;
	RefreshDetails();
	RefreshState();
}

void RichPresence::SetButtonLabel(MString label)
{
	buttonLabel = label;
}

void RichPresence::SetButtonUrl(MString url)
{
	buttonUrl = url;
}

void RichPresence::SetIdleMinutes(int minutes)
{
	idleMinutes = std::clamp(minutes, 1, 240);
	CheckIdle();
}

void RichPresence::SetIdleAction(MString action)
{
	if (action == "hide")
		idleAction = IdleAction::Hide;
	else if (action == "off")
		idleAction = IdleAction::Off;
	else
		idleAction = IdleAction::Show;
	CheckIdle();
	RefreshDetails();
}
