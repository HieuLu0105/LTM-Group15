# Embedded sensors (Windows)
1. Download the official LibreHardwareMonitor release that targets .NET Framework (compatible with installed .NET Framework 4.8/4.8.1): https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases
2. Copy LibreHardwareMonitorLib.dll, companion DLLs, required native dependencies and license notices from the same release into libs/. Do not mix target frameworks. DLLs are not included in this archive.
3. Run `py -m pip install -r requirements.txt`.
4. Close LibreHardwareMonitor GUI, open PowerShell as Administrator, set your existing Telegram environment variables and run `py app.py`. Check Hardware / Live sensors. HTTP and WMI remain optional fallbacks. Unsupported sensors remain unavailable.
5. Run build.bat on Windows after placing the DLLs in libs/. Test dist/NetPulse.exe on another Windows machine with compatible .NET Framework and drivers. Some sensors require administrator privileges; no guarantee of full sensor coverage. Build and DLL loading have not been tested on Windows.
