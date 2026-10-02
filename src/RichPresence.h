#pragma once
#include <chrono>
#include <optional>
#include <string>
#include <maya/MTimerMessage.h>
#include <maya/MString.h>

#include "discordpp.h"


template <typename T> class Singleton
{
protected:
	Singleton() = default;
	~Singleton() = default;

    inline static T* instance;


public:
    Singleton(Singleton& other) = delete;
    void operator=(const Singleton&) = delete;


	inline static T* GetInstance()
	{
		if (instance == nullptr)
		{
			instance = new T();
		}
		return instance;
	}

	inline static void DeleteInstance()
	{
		if (instance != nullptr)
		{
			delete instance;
			instance = nullptr;
		}
	}
};


class RichPresence : public Singleton<RichPresence>
{
private:
	inline static const uint64_t APPLICATION_ID = 1119332858394316880;
	// Folder the plug-in was loaded from, plug-ins/<version> inside the module
	inline static MString pluginDirectory;
	// Maya logo uploaded to the Discord application
	inline static const std::string LARGE_IMAGE = "newicon";
	MString dDetails;
	MString dState;
	discordpp::ActivityTimestamps dTimestamp;
	bool resetTimeOnChange = false;

	// What the activity is built from
	MString sceneName;
	bool sceneModified = false;
	bool displayScene = false;
	bool displayProject = false;
	bool displayTask = false;
	bool contextScriptAvailable = false;
	MString task;
	MString projectName; // empty with Maya's default project
	MString sceneStats;
	MString mayaVersion;
	MString rendererName;
	MString buttonLabel;
	MString buttonUrl;

	// Text written by the user to replace either line, with {task}, {scene}, {project} and {stats}
	MString customDetails;
	MString customState;
	bool customTextWhileIdle = false;

	// After a while without using Maya, show "Idle" or hide the status, and pause the timer
	enum class IdleAction { Show, Hide, Off };
	IdleAction idleAction = IdleAction::Show;
	int idleMinutes = 10;
	bool idle = false;
	bool presenceCleared = false;
	unsigned long lastInputTick = 0;

	MCallbackId projectChangeCallbackId = -1;
	std::vector<MCallbackId> sceneCallbackIds;
	MCallbackId runCallbacksTimerId = -1;

	inline static std::unique_ptr<discordpp::Client> client;
	inline static discordpp::Activity activity;

	using Clock = std::chrono::steady_clock;
	// Discord accepts 5 updates per 20 seconds
	inline static const Clock::duration UPDATE_INTERVAL = std::chrono::seconds(4);
	inline static const Clock::duration RETRY_INTERVAL = std::chrono::seconds(15);
	// Discord forgets the activity when it restarts, so it is sent again once in a while
	inline static const Clock::duration REFRESH_INTERVAL = std::chrono::seconds(60);
	// Maya has no callback for the task, unsaved changes or the renderer, so they are polled
	inline static const Clock::duration POLL_INTERVAL = std::chrono::seconds(2);
	// Scene statistics change slowly and cost a little more to read
	inline static const Clock::duration STATS_INTERVAL = std::chrono::seconds(10);

	bool updatesBlocked = false;
	bool updatePending = false;
	bool updateInFlight = false;
	std::optional<discordpp::Activity> lastSentActivity;
	Clock::time_point lastUpdateSent{};
	Clock::time_point nextUpdateAllowed{};
	Clock::time_point nextPoll{};
	Clock::time_point nextStatsPoll{};
	Clock::time_point lastUserActivity{};

	void BuildActivity();
	void FlushUpdate();
	void SendUpdate();
	void RefreshDetails();
	void PollMayaState();
	bool NeedsSceneStats() const;
	bool RefreshSceneStats();

	MString SceneText() const;
	bool TemplatesUse(const MString& placeholder) const;
	bool UsesCustomText(const MString& text) const { return text.length() && (!idle || customTextWhileIdle); }
	MString ExpandTemplate(const MString& text) const;

	bool UserInputInMaya();
	void RegisterUserActivity();
	void CheckIdle();
	void LeaveIdle();
	bool IsHidden() const { return idle && idleAction == IdleAction::Hide; }

	static void OnTimer(float elapsedTime, float lastTime, void* clientData);
	static void OnUpdateResult(const discordpp::ClientResult& result);

public:
    RichPresence();
    ~RichPresence();

	static void SetPluginDirectory(const MString& directory) { pluginDirectory = directory; }

	void BlockUpdates() { updatesBlocked = true; };
	void UnblockUpdates() { updatesBlocked = false; };

	void Enable();
	void Disable();

	void Initialize();
	void Update();

	void SetDetails(MString details);
	void SetState(MString state);
	void RefreshTimestamp();
	void UpdateSceneName();
	void RefreshState();

	void RegisterSceneCallbacks();
	void RemoveSceneCallbacks();

	void RegisterProjectCallback();
	void RemoveProjectCallback();

	static void OnProjectChange(void* clientData);
	static void OnFileChange(void* clientData);
	static void OnFileSave(void* clientData);

	void SetResetTimeOnChange(bool reset);
	void SetDisplayTask(bool display);
	void SetButtonLabel(MString label);
	void SetButtonUrl(MString url);
	void SetIdleMinutes(int minutes);
	void SetIdleAction(MString action);
	void SetDisplayScene(bool display);
	void SetDisplayProject(bool display);
	void SetCustomDetails(MString text);
	void SetCustomState(MString text);
	void SetCustomTextWhileIdle(bool keep);
};
