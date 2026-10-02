#include <maya/MFnPlugin.h>
#include <maya/MFileIO.h>
#include <maya/MString.h>
#include <maya/MStatus.h>
#include <maya/MGlobal.h>
#include <maya/MSceneMessage.h>

#define DISCORDPP_IMPLEMENTATION
#include "RichPresenceCmd.h"

MCallbackId closingCallbackId;


void OnMayaExiting(void* clientData)
{
	RichPresence::DeleteInstance();
}


MStatus initializePlugin(MObject obj)
{
	MFnPlugin fnPlugin(obj, "Aron Amao", "2.2", "Any");
	MStatus status = fnPlugin.registerCommand("richPresence", RichPresenceCmd::creator, RichPresenceCmd::NewSyntax);
	if (!status) {
		MGlobal::displayError("Failed to register richPresence command: " + status.errorString());
		return status;
	}
	closingCallbackId = MSceneMessage::addCallback(MSceneMessage::kMayaExiting, OnMayaExiting);
	RichPresence::SetPluginDirectory(fnPlugin.loadPath());
	RichPresence::GetInstance()->Enable();
	RichPresenceCmd::AddMenu();
	RichPresenceCmd::ApplySavedSettings();
	// Sends the first status, unless the saved settings above already did
	RichPresence::GetInstance()->Update();

	return MS::kSuccess;
}

MStatus uninitializePlugin(MObject obj)
{
	MMessage::removeCallback(closingCallbackId);
	MStatus status = MFnPlugin(obj).deregisterCommand("richPresence");
	CHECK_MSTATUS(status);
	// Always cleaned up, even if the command couldn't be removed: the timer and scene callbacks
	// point into this plug-in, and would crash Maya once it is unloaded
	RichPresenceCmd::RemoveMenu();
	RichPresence::DeleteInstance();
	return status;
}
