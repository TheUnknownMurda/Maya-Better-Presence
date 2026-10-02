@echo off
setlocal
rem Builds DRPForMaya.mll for one Maya version without CMake, straight into the module folder.
rem   build.bat 2027                              uses the headers of the installed Maya 2027
rem   build.bat 2025 E:\maya_devkits\2025\devkitBase   uses an extracted Maya devkit

set MAYA_VERSION=%~1
if "%MAYA_VERSION%"=="" (
    echo Usage: build.bat ^<maya version^> [devkitBase folder]
    exit /b 1
)
set MAYA_SDK=%~2
if "%MAYA_SDK%"=="" set "MAYA_SDK=C:\Program Files\Autodesk\Maya%MAYA_VERSION%"
if not exist "%MAYA_SDK%\include\maya\MFnPlugin.h" (
    echo Maya headers not found in "%MAYA_SDK%\include"
    exit /b 1
)

for /f "usebackq delims=" %%i in (`"%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -property installationPath`) do set "VS_PATH=%%i"
call "%VS_PATH%\VC\Auxiliary\Build\vcvars64.bat" >nul 2>nul || (
    echo Visual Studio 2022 C++ build tools not found
    exit /b 1
)

set "ROOT=%~dp0"
set "DISCORD_SDK=%ROOT%third_party\discord_social_sdk"
set "OUT=%ROOT%build\%MAYA_VERSION%"
if not exist "%OUT%" mkdir "%OUT%"
pushd "%OUT%"

cl /nologo /c /std:c++17 /MD /O2 /EHsc /GR /W3 /permissive- /Zc:__cplusplus /utf-8 ^
    /DNT_PLUGIN /DREQUIRE_IOSTREAM /D_BOOL /DBits64_ /D_WINDOWS /DWIN32 /DNDEBUG ^
    /D_CRT_SECURE_NO_DEPRECATE /D_HAS_ITERATOR_DEBUGGING=0 /D_SECURE_SCL=0 ^
    /I"%MAYA_SDK%\include" /I"%DISCORD_SDK%\include" /I"%ROOT%third_party\mini" ^
    "%ROOT%src\pluginMain.cpp" "%ROOT%src\RichPresence.cpp" "%ROOT%src\RichPresenceCmd.cpp" || goto :failed

link /nologo /DLL /OUT:DRPForMaya.mll /export:initializePlugin /export:uninitializePlugin ^
    pluginMain.obj RichPresence.obj RichPresenceCmd.obj ^
    /LIBPATH:"%MAYA_SDK%\lib" OpenMaya.lib Foundation.lib user32.lib ^
    "%DISCORD_SDK%\lib\release\discord_partner_sdk.lib" || goto :failed

popd
if not exist "%ROOT%module\plug-ins\%MAYA_VERSION%" mkdir "%ROOT%module\plug-ins\%MAYA_VERSION%"
copy /y "%OUT%\DRPForMaya.mll" "%ROOT%module\plug-ins\%MAYA_VERSION%\" >nul || exit /b 1
copy /y "%DISCORD_SDK%\bin\release\discord_partner_sdk.dll" "%ROOT%module\bin\" >nul || exit /b 1
echo Built module\plug-ins\%MAYA_VERSION%\DRPForMaya.mll
exit /b 0

:failed
popd
echo Build failed
exit /b 1
