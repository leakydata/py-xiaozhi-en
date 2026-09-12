// The application entry point
import QtQuick
import QtQuick.Window

import "windows"

// The main window is the root element. It starts hidden, and QmlAppHost.show_root decides whether it takes focus.
MainWindow {
    id: mainWindow
    visible: false

    // the settings window, loaded on demand through a Loader as a window of its own
    Loader {
        id: settingsLoader
        active: false
        source: "windows/SettingsWindow.qml"

        onLoaded: {
            item.visible = true
            item.raise()
            item.requestActivate()
        }
    }

    // the eventBridge signals drive the settings window
    Connections {
        target: eventBridge

        function onShowSettingsWindow() {
            if (settingsLoader.active) {
                // already loaded, so just show it
                settingsLoader.item.visible = true
                settingsLoader.item.raise()
                settingsLoader.item.requestActivate()
            } else {
                // first time through, load it
                settingsLoader.active = true
            }
        }
    }
}
