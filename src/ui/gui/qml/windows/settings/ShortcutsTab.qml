// Shortcuts settings page
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../theme"
import "../../controls"

ScrollView {
    id: root
    clip: true
    contentWidth: availableWidth
    ScrollBar.vertical.policy: ScrollBar.AlwaysOn
    // the always-on bar is an overlay and reserves no space; without this
    // the right-hand controls sit underneath it
    rightPadding: 14

    ColumnLayout {
        width: root.availableWidth
        spacing: Theme.spacingLg

        // Page title
        Text {
            text: "Shortcut Settings"
            font.pixelSize: Theme.fontSizeXl
            font.weight: Font.DemiBold
            color: Theme.textPrimary
        }

        // Basic settings
        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingMd

            Text {
                text: "Basic Settings"
                font.pixelSize: Theme.fontSizeMd
                font.weight: Font.Medium
                color: Theme.textSecondary
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spacingMd

                Text {
                    text: "Enable Global Shortcuts"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                }

                Item { Layout.fillWidth: true }

                XSwitch {
                    checked: settingsModel ? settingsModel.shortcutsEnabled : false
                    onToggled: if (settingsModel) settingsModel.shortcutsEnabled = checked
                }
            }
        }

        // Divider
        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: Theme.divider
        }

        // Shortcut configuration
        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingMd
            opacity: settingsModel && settingsModel.shortcutsEnabled ? 1.0 : 0.5
            enabled: settingsModel ? settingsModel.shortcutsEnabled : false

            Text {
                text: "Shortcut Configuration"
                font.pixelSize: Theme.fontSizeMd
                font.weight: Font.Medium
                color: Theme.textSecondary
            }

            // Push to talk
            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spacingMd

                Text {
                    text: "Push to Talk"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textPrimary
                    Layout.preferredWidth: 80
                }

                XComboBox {
                    id: manualModCombo
                    Layout.preferredWidth: 100
                    model: ["Ctrl", "Alt", "Shift", "Cmd"]
                    currentIndex: {
                        var mod = settingsModel ? settingsModel.shortcutManualModifier : "ctrl"
                        if (mod === "alt") return 1
                        if (mod === "shift") return 2
                        if (mod === "cmd") return 3
                        return 0  // ctrl
                    }
                    onActivated: function(index) {
                        var options = ["ctrl", "alt", "shift", "cmd"]
                        if (settingsModel) settingsModel.shortcutManualModifier = options[index]
                    }
                }

                Text { text: "+"; font.pixelSize: Theme.fontSizeSm; color: Theme.textSecondary }

                TextField {
                    id: manualKeyField
                    Layout.preferredWidth: 50
                    text: settingsModel ? settingsModel.shortcutManualKey : ""
                    onEditingFinished: if (settingsModel) settingsModel.shortcutManualKey = text.toLowerCase()
                    maximumLength: 1
                    horizontalAlignment: Text.AlignHCenter
                    font.pixelSize: Theme.fontSizeSm
                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: Theme.backgroundSecondary
                        border.color: manualKeyField.activeFocus ? Theme.primary : "transparent"
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: "Hold to record"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textPlaceholder
                }
            }

            Rectangle { Layout.fillWidth: true; height: 1; color: Theme.divider }

            // Auto conversation
            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spacingMd

                Text {
                    text: "Auto Conversation"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textPrimary
                    Layout.preferredWidth: 80
                }

                XComboBox {
                    id: autoModCombo
                    Layout.preferredWidth: 100
                    model: ["Ctrl", "Alt", "Shift", "Cmd"]
                    currentIndex: {
                        var mod = settingsModel ? settingsModel.shortcutAutoModifier : "ctrl"
                        if (mod === "alt") return 1
                        if (mod === "shift") return 2
                        if (mod === "cmd") return 3
                        return 0
                    }
                    onActivated: function(index) {
                        var options = ["ctrl", "alt", "shift", "cmd"]
                        if (settingsModel) settingsModel.shortcutAutoModifier = options[index]
                    }
                }

                Text { text: "+"; font.pixelSize: Theme.fontSizeSm; color: Theme.textSecondary }

                TextField {
                    id: autoKeyField
                    Layout.preferredWidth: 50
                    text: settingsModel ? settingsModel.shortcutAutoKey : ""
                    onEditingFinished: if (settingsModel) settingsModel.shortcutAutoKey = text.toLowerCase()
                    maximumLength: 1
                    horizontalAlignment: Text.AlignHCenter
                    font.pixelSize: Theme.fontSizeSm
                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: Theme.backgroundSecondary
                        border.color: autoKeyField.activeFocus ? Theme.primary : "transparent"
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: "Toggle auto conversation"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textPlaceholder
                }
            }

            Rectangle { Layout.fillWidth: true; height: 1; color: Theme.divider }

            // Abort conversation
            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spacingMd

                Text {
                    text: "Abort Conversation"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textPrimary
                    Layout.preferredWidth: 80
                }

                XComboBox {
                    id: abortModCombo
                    Layout.preferredWidth: 100
                    model: ["Ctrl", "Alt", "Shift", "Cmd"]
                    currentIndex: {
                        var mod = settingsModel ? settingsModel.shortcutAbortModifier : "ctrl"
                        if (mod === "alt") return 1
                        if (mod === "shift") return 2
                        if (mod === "cmd") return 3
                        return 0
                    }
                    onActivated: function(index) {
                        var options = ["ctrl", "alt", "shift", "cmd"]
                        if (settingsModel) settingsModel.shortcutAbortModifier = options[index]
                    }
                }

                Text { text: "+"; font.pixelSize: Theme.fontSizeSm; color: Theme.textSecondary }

                TextField {
                    id: abortKeyField
                    Layout.preferredWidth: 50
                    text: settingsModel ? settingsModel.shortcutAbortKey : ""
                    onEditingFinished: if (settingsModel) settingsModel.shortcutAbortKey = text.toLowerCase()
                    maximumLength: 1
                    horizontalAlignment: Text.AlignHCenter
                    font.pixelSize: Theme.fontSizeSm
                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: Theme.backgroundSecondary
                        border.color: abortKeyField.activeFocus ? Theme.primary : "transparent"
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: "Stop the current conversation immediately"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textPlaceholder
                }
            }

            Rectangle { Layout.fillWidth: true; height: 1; color: Theme.divider }

            // Toggle mode
            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spacingMd

                Text {
                    text: "Toggle Mode"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textPrimary
                    Layout.preferredWidth: 80
                }

                XComboBox {
                    id: modeModCombo
                    Layout.preferredWidth: 100
                    model: ["Ctrl", "Alt", "Shift", "Cmd"]
                    currentIndex: {
                        var mod = settingsModel ? settingsModel.shortcutModeModifier : "ctrl"
                        if (mod === "alt") return 1
                        if (mod === "shift") return 2
                        if (mod === "cmd") return 3
                        return 0
                    }
                    onActivated: function(index) {
                        var options = ["ctrl", "alt", "shift", "cmd"]
                        if (settingsModel) settingsModel.shortcutModeModifier = options[index]
                    }
                }

                Text { text: "+"; font.pixelSize: Theme.fontSizeSm; color: Theme.textSecondary }

                TextField {
                    id: modeKeyField
                    Layout.preferredWidth: 50
                    text: settingsModel ? settingsModel.shortcutModeKey : ""
                    onEditingFinished: if (settingsModel) settingsModel.shortcutModeKey = text.toLowerCase()
                    maximumLength: 1
                    horizontalAlignment: Text.AlignHCenter
                    font.pixelSize: Theme.fontSizeSm
                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: Theme.backgroundSecondary
                        border.color: modeKeyField.activeFocus ? Theme.primary : "transparent"
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: "Switch between manual and auto mode"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textPlaceholder
                }
            }

            Rectangle { Layout.fillWidth: true; height: 1; color: Theme.divider }

            // Show/hide window
            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spacingMd

                Text {
                    text: "Show/Hide"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textPrimary
                    Layout.preferredWidth: 80
                }

                XComboBox {
                    id: windowModCombo
                    Layout.preferredWidth: 100
                    model: ["Ctrl", "Alt", "Shift", "Cmd"]
                    currentIndex: {
                        var mod = settingsModel ? settingsModel.shortcutWindowModifier : "ctrl"
                        if (mod === "alt") return 1
                        if (mod === "shift") return 2
                        if (mod === "cmd") return 3
                        return 0
                    }
                    onActivated: function(index) {
                        var options = ["ctrl", "alt", "shift", "cmd"]
                        if (settingsModel) settingsModel.shortcutWindowModifier = options[index]
                    }
                }

                Text { text: "+"; font.pixelSize: Theme.fontSizeSm; color: Theme.textSecondary }

                TextField {
                    id: windowKeyField
                    Layout.preferredWidth: 50
                    text: settingsModel ? settingsModel.shortcutWindowKey : ""
                    onEditingFinished: if (settingsModel) settingsModel.shortcutWindowKey = text.toLowerCase()
                    maximumLength: 1
                    horizontalAlignment: Text.AlignHCenter
                    font.pixelSize: Theme.fontSizeSm
                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: Theme.backgroundSecondary
                        border.color: windowKeyField.activeFocus ? Theme.primary : "transparent"
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: "Toggle main window visibility"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textPlaceholder
                }
            }
        }

        // Divider
        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: Theme.divider
        }

        // Hint text
        Text {
            Layout.fillWidth: true
            text: "Shortcuts work globally. Make sure they do not conflict with system or other application shortcuts."
            font.pixelSize: Theme.fontSizeSm
            color: Theme.textPlaceholder
            wrapMode: Text.WordWrap
        }

        Item { Layout.fillHeight: true }
    }
}
