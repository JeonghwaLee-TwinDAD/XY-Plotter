@echo off
echo Installing PyInstaller...
python -m pip install pyinstaller

echo.
echo Building FlowGrind XY Plotter executable...
python -m PyInstaller --name "FlowGrind_XY_Plotter" --console --clean --noconfirm --copy-metadata nitypes --copy-metadata nidaqmx main.py

echo.
echo Build complete! You can find your executable inside the newly created 'dist\FlowGrind_XY_Plotter' folder.
pause
