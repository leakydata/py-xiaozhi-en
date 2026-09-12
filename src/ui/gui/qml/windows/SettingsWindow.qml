// Settings window - mirrors the old PyQt5 layout
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"
import "../components"
import "settings"

AppWindow {
    id: root

    width: 700
    height: 550
    minimumWidth: 600
    minimumHeight: 450
    title: "Settings"
    visible: false

    // Tab configuration
    readonly property var tabConfig: [
        { name: "System Options", component: "SystemOptionsTab.qml" },
        { name: "MCP Tools", component: "McpToolsTab.qml" },
        { name: "Wake Word", component: "WakeWordTab.qml" },
        { name: "Camera", component: "CameraTab.qml" },
        { name: "Audio Devices", component: "AudioDeviceTab.qml" },
        { name: "Shortcuts", component: "ShortcutsTab.qml" },
        { name: "Music", component: "MusicTab.qml" }
    ]

    // use ColumnLayout directly; no extra Rectangle layer needed
    ColumnLayout {
        anchors.fill: parent
        spacing: 0

            // Custom title bar - adapts per platform
            TitleBar {
                Layout.fillWidth: true
                title: "Settings"
                showMaximize: true
                onMinimizeClicked: root.showMinimized()
                onMaximizeClicked: {
                    if (root.visibility === Window.FullScreen || root.visibility === Window.Maximized) {
                        root.showNormal()
                    } else {
                        root.showMaximized()
                    }
                }
                onCloseClicked: root.close()
            }

            // Content area
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: Theme.background

                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 0
                    spacing: 0

                    // Left navigation bar
                    Rectangle {
                        Layout.preferredWidth: 150
                        Layout.fillHeight: true
                        color: Theme.backgroundSecondary

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: Theme.spacingMd
                            spacing: Theme.spacingXs

                            Repeater {
                                model: tabConfig

                                delegate: Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 40
                                    radius: Theme.radiusMd
                                    color: tabBar.currentIndex === index ? Theme.primaryLight : (navMouse.containsMouse ? Theme.backgroundHover : "transparent")

                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: Theme.spacingMd
                                        anchors.rightMargin: Theme.spacingMd
                                        spacing: Theme.spacingSm

                                        // Icon area (optional)
                                        Rectangle {
                                            width: 4
                                            height: 20
                                            radius: 2
                                            color: tabBar.currentIndex === index ? Theme.primary : "transparent"
                                        }

                                        Text {
                                            Layout.fillWidth: true
                                            text: modelData.name
                                            font.pixelSize: Theme.fontSizeMd
                                            color: tabBar.currentIndex === index ? Theme.primary : Theme.textSecondary
                                            elide: Text.ElideRight
                                        }
                                    }

                                    MouseArea {
                                        id: navMouse
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: tabBar.currentIndex = index
                                    }
                                }
                            }

                            Item { Layout.fillHeight: true }
                        }
                    }

                    // Divider
                    Rectangle {
                        Layout.preferredWidth: 1
                        Layout.fillHeight: true
                        color: Theme.border
                    }

                    // Right-hand content area
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        color: Theme.background

                        StackLayout {
                            id: tabBar
                            anchors.fill: parent
                            anchors.margins: Theme.spacingXl
                            currentIndex: 0

                            // System options
                            SystemOptionsTab {}

                            // MCP tools
                            McpToolsTab {}

                            // Wake word
                            WakeWordTab {}

                            // Camera
                            CameraTab {}

                            // Audio devices
                            AudioDeviceTab {}

                            // Shortcuts
                            ShortcutsTab {}

                            // Music
                            MusicTab {}
                        }
                    }
                }
            }

            // Bottom button bar
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 60
                color: Theme.backgroundSecondary

                // Top divider
                Rectangle {
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.right: parent.right
                    height: 1
                    color: Theme.border
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.spacingXl
                    anchors.rightMargin: Theme.spacingXl
                    spacing: Theme.spacingMd

                    // Status message
                    Text {
                        id: statusText
                        Layout.fillWidth: true
                        font.pixelSize: Theme.fontSizeSm
                        color: Theme.textPlaceholder
                        elide: Text.ElideRight

                        Connections {
                            target: settingsModel
                            function onStatusMessage(msg) {
                                statusText.text = msg
                                statusTimer.restart()
                            }
                        }

                        Timer {
                            id: statusTimer
                            interval: 5000
                            onTriggered: statusText.text = ""
                        }
                    }

                    // Reset button
                    Button {
                        id: resetBtn
                        Layout.preferredWidth: 80
                        Layout.preferredHeight: 34
                        text: "Reset"

                        background: Rectangle {
                            color: resetBtn.pressed ? Theme.errorLight : (resetBtn.hovered ? Theme.errorLight : "transparent")
                            border.color: Theme.error
                            border.width: 1
                            radius: Theme.radiusSm
                        }

                        contentItem: Text {
                            text: resetBtn.text
                            font.pixelSize: Theme.fontSizeSm
                            color: Theme.error
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }

                        onClicked: {
                            settingsModel.reload()
                        }
                    }

                    // Cancel button
                    Button {
                        id: cancelBtn
                        Layout.preferredWidth: 80
                        Layout.preferredHeight: 34
                        text: "Cancel"

                        background: Rectangle {
                            color: cancelBtn.pressed ? Theme.divider : (cancelBtn.hovered ? Theme.backgroundHover : Theme.backgroundSecondary)
                            radius: Theme.radiusSm
                            border.width: 1
                            border.color: Theme.border
                        }

                        contentItem: Text {
                            text: cancelBtn.text
                            font.pixelSize: Theme.fontSizeSm
                            color: Theme.textSecondary
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }

                        onClicked: root.close()
                    }

                    // Save button
                    Button {
                        id: saveBtn
                        Layout.preferredWidth: 80
                        Layout.preferredHeight: 34
                        text: "Save"

                        background: Rectangle {
                            color: saveBtn.pressed ? Theme.primaryPressed : (saveBtn.hovered ? Theme.primaryHover : Theme.primary)
                            radius: Theme.radiusSm
                        }

                        contentItem: Text {
                            text: saveBtn.text
                            font.pixelSize: Theme.fontSizeSm
                            color: "white"
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }

                        onClicked: {
                            // take focus first so the active TextField fires editingFinished and writes back
                            saveBtn.forceActiveFocus()
                            settingsModel.save()
                            root.close()
                        }
                    }
            }
        }
    }
}
