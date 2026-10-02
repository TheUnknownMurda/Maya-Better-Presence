#include "RichPresenceCmd.h"

MStatus RichPresenceCmd::doIt(const MArgList& argList)
{
	MStatus status;
	const MArgDatabase argData(syntax(), argList, &status);
	CHECK_MSTATUS_AND_RETURN_IT(status);

	ptr->BlockUpdates();

	if (argData.isFlagSet("-d"))
	{
		MString details;
		status = argData.getFlagArgument("-d", 0, details);
		ptr->SetDetails(details);
	}
	if (argData.isFlagSet("-st"))
	{
		MString state;
		status = argData.getFlagArgument("-st", 0, state);
		ptr->SetState(state);
	}
	if (argData.isFlagSet("-rt"))
	{
		ptr->RefreshTimestamp();
	}
	if (argData.isFlagSet("-ds"))
	{
		bool displayScene;
		status = argData.getFlagArgument("-ds", 0, displayScene);
		if (status == MStatus::kSuccess)
		{
			ptr->SetDisplayScene(displayScene);
		}
	}
	if (argData.isFlagSet("-dp"))
	{
		bool displayProject;
		status = argData.getFlagArgument("-dp", 0, displayProject);
		if (status == MStatus::kSuccess)
		{
			ptr->SetDisplayProject(displayProject);
		}
	}
	if (argData.isFlagSet("-roc"))
	{
		bool resetTimeOnChange;
		status = argData.getFlagArgument("-roc", 0, resetTimeOnChange);
		if (status == MStatus::kSuccess)
		{
			ptr->SetResetTimeOnChange(resetTimeOnChange);
		}
	}
	if (argData.isFlagSet("-dt"))
	{
		bool displayTask;
		status = argData.getFlagArgument("-dt", 0, displayTask);
		if (status == MStatus::kSuccess)
		{
			ptr->SetDisplayTask(displayTask);
		}
	}
	if (argData.isFlagSet("-bl"))
	{
		MString label;
		status = argData.getFlagArgument("-bl", 0, label);
		ptr->SetButtonLabel(label);
	}
	if (argData.isFlagSet("-bu"))
	{
		MString url;
		status = argData.getFlagArgument("-bu", 0, url);
		ptr->SetButtonUrl(url);
	}
	if (argData.isFlagSet("-im"))
	{
		int minutes;
		status = argData.getFlagArgument("-im", 0, minutes);
		if (status == MStatus::kSuccess)
		{
			ptr->SetIdleMinutes(minutes);
		}
	}
	if (argData.isFlagSet("-ia"))
	{
		MString action;
		status = argData.getFlagArgument("-ia", 0, action);
		ptr->SetIdleAction(action);
	}
	if (argData.isFlagSet("-cd"))
	{
		MString text;
		status = argData.getFlagArgument("-cd", 0, text);
		ptr->SetCustomDetails(text);
	}
	if (argData.isFlagSet("-cs"))
	{
		MString text;
		status = argData.getFlagArgument("-cs", 0, text);
		ptr->SetCustomState(text);
	}
	if (argData.isFlagSet("-ci"))
	{
		bool keep;
		status = argData.getFlagArgument("-ci", 0, keep);
		if (status == MStatus::kSuccess)
		{
			ptr->SetCustomTextWhileIdle(keep);
		}
	}

	ptr->UnblockUpdates();
	ptr->Update();
	return status;
}

MSyntax RichPresenceCmd::NewSyntax()
{
	MSyntax syntax{};
	syntax.setMaxObjects(0);
	syntax.enableEdit(false);
	syntax.addFlag("-d", "-details", MSyntax::kString);
	syntax.addFlag("-st", "-state", MSyntax::kString);
	syntax.addFlag("-ds", "-displayScene", MSyntax::kBoolean);
	syntax.addFlag("-dp", "-displayProject", MSyntax::kBoolean);
	syntax.addFlag("-roc", "-resetTimeOnChange", MSyntax::kBoolean);
	syntax.addFlag("-rt", "-resetTime", MSyntax::kNoArg);
	syntax.addFlag("-dt", "-displayTask", MSyntax::kBoolean);
	syntax.addFlag("-bl", "-buttonLabel", MSyntax::kString);
	syntax.addFlag("-bu", "-buttonUrl", MSyntax::kString);
	syntax.addFlag("-im", "-idleMinutes", MSyntax::kLong);
	// "show" to show "Idle", "hide" to hide the status, "off" to do nothing
	syntax.addFlag("-ia", "-idleAction", MSyntax::kString);
	// Custom text for either line, with {task}, {scene}, {project} and {stats}. Empty for automatic text.
	syntax.addFlag("-cd", "-customDetails", MSyntax::kString);
	syntax.addFlag("-cs", "-customState", MSyntax::kString);
	syntax.addFlag("-ci", "-customTextWhileIdle", MSyntax::kBoolean);
	return syntax;
}
