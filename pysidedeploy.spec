[app]
title = TeslaCamViewer
project_dir = .
input_file = qtTeslaCam.py
project_file = teslacamviewer.pyproject
exec_directory = dist
icon =

[python]
python_path = python
packages = Nuitka==2.7.11,opencv-python,psutil,PyYAML

[qt]
modules = QtCore,QtGui,QtWidgets,QtMultimedia,QtWebEngineCore,QtWebEngineWidgets
qml_files =
excluded_qml_plugins =
plugins = multimedia,networkinformation,platforminputcontexts,position

[nuitka]
mode = standalone
extra_args = --quiet --noinclude-qt-translations --assume-yes-for-downloads --include-data-dir=leaflet=leaflet
