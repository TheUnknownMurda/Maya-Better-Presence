#pragma once
#include "RichPresence.h"

#include <maya/MPxCommand.h>
#include <maya/MSyntax.h>
#include <maya/MGlobal.h>
#include <maya/MArgDatabase.h>


class RichPresenceCmd : public MPxCommand
{
private:
	RichPresence* ptr = RichPresence::GetInstance();

public:
	RichPresenceCmd() = default;

	MStatus doIt(const MArgList& argList) override;

	static void* creator()
	{
		return new RichPresenceCmd;
	}

	static MSyntax NewSyntax();

	inline static void AddMenu()
	{
	#ifdef DEBUG
		MGlobal::executePythonCommand("import RichPresenceUI\nfrom importlib import reload\nreload(RichPresenceUI)");
	#endif
		MGlobal::executePythonCommand("from RichPresenceUI import RichPresenceUI\nRichPresenceUI.add_menu()");
	}

	// Text settings are read by Python, which decodes config.ini the same way it was written
	inline static void ApplySavedSettings()
	{
		MGlobal::executePythonCommand("from RichPresenceUI import RichPresenceUI\nRichPresenceUI.apply_saved_settings()");
	}

	inline static void RemoveMenu()
	{
		MGlobal::executePythonCommand("from RichPresenceUI import RichPresenceUI\nRichPresenceUI.remove_menu()");
	}
};
