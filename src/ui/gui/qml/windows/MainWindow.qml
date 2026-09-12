// The main window
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"
import "../components"

AppWindow {
    id: root

    width: 420
    height: 520
    minimumWidth: 360
    minimumHeight: 420
    title: ""
    // QmlAppHost.show_root decides when this appears, so loading the QML does not steal focus
    visible: false

    // a ColumnLayout directly; no extra Rectangle layer is needed
    // AppWindow already provides the rounded container
    ColumnLayout {
        anchors.fill: parent
        spacing: 0

            // the custom title bar, which adapts to the platform
            TitleBar {
                Layout.fillWidth: true
                showMaximize: true
                onMinimizeClicked: root.showMinimized()
                onMaximizeClicked: {
                    if (root.visibility === Window.FullScreen || root.visibility === Window.Maximized) {
                        root.showNormal()
                    } else {
                        root.showMaximized()
                    }
                }
                onCloseClicked: {
                    if (eventBridge) eventBridge.onQuitRequest()
                }
            }

            // the status card
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: "transparent"

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: Theme.spacingMd
                    spacing: Theme.spacingMd

                    // status label
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 40
                        color: Theme.primaryLight
                        radius: Theme.radiusMd

                        Text {
                            anchors.centerIn: parent
                            text: (mainModel && mainModel.statusText) ? mainModel.statusText : "Idle"
                            font.pixelSize: Theme.fontSizeMd
                            font.weight: Font.Bold
                            color: Theme.primaryText
                        }
                    }

                    // the emotion display
                    // useProceduralAvatar: true = the drawn avatar (its mouth follows the audio)
                    //                      false = the original GIF emotions
                    Item {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.minimumHeight: 80

                        // chosen in the settings: person | simple | gif
                        property string avatarStyle: (settingsModel && settingsModel.avatarStyle)
                            ? settingsModel.avatarStyle : "person"
                        property bool useProceduralAvatar: avatarStyle !== "gif"
                        property string currentEmotionUrl: (mainModel && mainModel.emotionUrl) ? mainModel.emotionUrl : ""

                        Avatar {
                            anchors.centerIn: parent
                            width: Math.max(Math.min(parent.width, parent.height) * 0.95, 60)
                            height: width
                            visible: parent.useProceduralAvatar
                            style: parent.avatarStyle
                            emotion: (mainModel && mainModel.emotionName) ? mainModel.emotionName : "neutral"
                            mode: (mainModel && mainModel.deviceState) ? mainModel.deviceState : "idle"
                            level: (mainModel && mainModel.audioLevel) ? mainModel.audioLevel : 0.0
                        }

                        AnimatedImage {
                            anchors.centerIn: parent
                            width: Math.max(Math.min(parent.width, parent.height) * 0.7, 60)
                            height: width
                            source: parent.currentEmotionUrl
                            fillMode: Image.PreserveAspectFit
                            playing: true
                            visible: !parent.useProceduralAvatar && parent.currentEmotionUrl.length > 0 && parent.currentEmotionUrl.indexOf("file://") === 0
                        }

                        Text {
                            anchors.centerIn: parent
                            text: parent.currentEmotionUrl.indexOf("file://") !== 0 ? (parent.currentEmotionUrl || "😊") : ""
                            font.pixelSize: 80
                            visible: !parent.useProceduralAvatar && parent.currentEmotionUrl.indexOf("file://") !== 0
                        }
                    }

                    // the chat and music lines
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 72
                        color: "transparent"

                        Column {
                            anchors.fill: parent
                            anchors.margins: Theme.spacingSm
                            spacing: Theme.spacingXs

                            Text {
                                width: parent.width
                                height: parent.height - (musicLineText.visible ? 22 : 0)
                                text: (mainModel && mainModel.ttsText) ? mainModel.ttsText : "Idle"
                                font.pixelSize: Theme.fontSizeSm
                                color: Theme.textSecondary
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                                wrapMode: Text.WordWrap
                                elide: Text.ElideRight
                            }

                            Text {
                                id: musicLineText
                                width: parent.width
                                visible: mainModel && mainModel.musicLine && mainModel.musicLine.length > 0
                                text: mainModel ? mainModel.musicLine : ""
                                font.pixelSize: Theme.fontSizeXs
                                color: Theme.textPlaceholder
                                horizontalAlignment: Text.AlignHCenter
                                elide: Text.ElideRight
                            }
                        }
                    }
                }
            }

            // the buttons
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 72
                color: Theme.backgroundSecondary

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.spacingMd
                    anchors.rightMargin: Theme.spacingMd
                    anchors.bottomMargin: 10
                    spacing: Theme.spacingSm

                    // manual mode button (click to start or stop recording)
                    Button {
                        id: manualBtn
                        Layout.preferredWidth: 100
                        Layout.fillWidth: true
                        Layout.maximumWidth: 140
                        Layout.preferredHeight: 38
                        text: (mainModel && mainModel.buttonText) ? mainModel.buttonText : "Hold to Talk"
                        visible: !(mainModel && mainModel.autoMode)

                        background: Rectangle {
                            color: manualBtn.pressed ? Theme.primaryPressed : (manualBtn.hovered ? Theme.primaryHover : Theme.primary)
                            radius: Theme.radiusMd
                        }

                        contentItem: Text {
                            text: manualBtn.text
                            font.pixelSize: Theme.fontSizeSm
                            color: "white"
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }

                        onClicked: if (eventBridge) eventBridge.onManualToggle()
                    }

                    // auto mode button
                    Button {
                        id: autoBtn
                        Layout.preferredWidth: 100
                        Layout.fillWidth: true
                        Layout.maximumWidth: 140
                        Layout.preferredHeight: 38
                        text: (mainModel && mainModel.buttonText) ? mainModel.buttonText : "Start Chat"
                        visible: mainModel && mainModel.autoMode

                        background: Rectangle {
                            color: autoBtn.pressed ? Theme.primaryPressed : (autoBtn.hovered ? Theme.primaryHover : Theme.primary)
                            radius: Theme.radiusMd
                        }

                        contentItem: Text {
                            text: autoBtn.text
                            font.pixelSize: Theme.fontSizeSm
                            color: "white"
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }

                        onClicked: if (eventBridge) eventBridge.onAutoStart()
                    }

                    // interrupt
                    Button {
                        id: abortBtn
                        Layout.preferredWidth: 80
                        Layout.fillWidth: true
                        Layout.maximumWidth: 120
                        Layout.preferredHeight: 38
                        text: "Interrupt"

                        background: Rectangle {
                            color: abortBtn.pressed ? Theme.divider : (abortBtn.hovered ? Theme.backgroundHover : Theme.backgroundSecondary)
                            radius: Theme.radiusMd
                            border.width: 1
                            border.color: Theme.border
                        }

                        contentItem: Text {
                            text: abortBtn.text
                            font.pixelSize: Theme.fontSizeSm
                            color: Theme.textPrimary
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }

                        onClicked: if (eventBridge) eventBridge.onAbort()
                    }

                    // the text box and send button
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 120
                        Layout.preferredHeight: 38
                        spacing: Theme.spacingSm

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 38
                            color: Theme.background
                            radius: Theme.radiusMd
                            border.color: textInput.activeFocus ? Theme.primary : Theme.border
                            border.width: 1

                            TextInput {
                                id: textInput
                                anchors.fill: parent
                                anchors.leftMargin: 10
                                anchors.rightMargin: 10
                                verticalAlignment: TextInput.AlignVCenter
                                font.pixelSize: Theme.fontSizeSm
                                color: Theme.textPrimary
                                selectByMouse: true
                                clip: true

                                Text {
                                    anchors.fill: parent
                                    text: "Type..."
                                    font: textInput.font
                                    color: Theme.textPlaceholder
                                    verticalAlignment: Text.AlignVCenter
                                    visible: !textInput.text && !textInput.activeFocus
                                }

                                Keys.onReturnPressed: sendText()
                            }
                        }

                        Button {
                            id: sendBtn
                            Layout.preferredWidth: 60
                            Layout.maximumWidth: 84
                            Layout.preferredHeight: 38
                            text: "Send"

                            background: Rectangle {
                                color: sendBtn.pressed ? Theme.primaryPressed : (sendBtn.hovered ? Theme.primaryHover : Theme.primary)
                                radius: Theme.radiusMd
                            }

                            contentItem: Text {
                                text: sendBtn.text
                                font.pixelSize: Theme.fontSizeSm
                                color: "white"
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }

                            onClicked: sendText()
                        }
                    }

                    // switch mode
                    Button {
                        id: modeBtn
                        Layout.preferredWidth: 80
                        Layout.fillWidth: true
                        Layout.maximumWidth: 120
                        Layout.preferredHeight: 38
                        text: (mainModel && mainModel.modeText) ? mainModel.modeText : "Manual Mode"

                        background: Rectangle {
                            color: modeBtn.pressed ? Theme.divider : (modeBtn.hovered ? Theme.backgroundHover : Theme.backgroundSecondary)
                            radius: Theme.radiusMd
                            border.width: 1
                            border.color: Theme.border
                        }

                        contentItem: Text {
                            text: modeBtn.text
                            font.pixelSize: Theme.fontSizeSm
                            color: Theme.textPrimary
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }

                        onClicked: if (eventBridge) eventBridge.onAutoToggle()
                    }

                    // settings
                    Button {
                        id: settingsBtn
                        Layout.preferredWidth: 80
                        Layout.fillWidth: true
                        Layout.maximumWidth: 120
                        Layout.preferredHeight: 38
                        text: "Settings"

                        background: Rectangle {
                            color: settingsBtn.pressed ? Theme.divider : (settingsBtn.hovered ? Theme.backgroundHover : Theme.backgroundSecondary)
                            radius: Theme.radiusMd
                            border.width: 1
                            border.color: Theme.border
                        }

                        contentItem: Text {
                            text: settingsBtn.text
                            font.pixelSize: Theme.fontSizeSm
                            color: Theme.textPrimary
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }

                        onClicked: if (eventBridge) eventBridge.onOpenSettings()
                    }

                    // Activity panel toggle. The dot turns live while a tool is
                    // running, so "is it thinking or wedged" is answerable at a
                    // glance without opening the panel.
                    Button {
                        id: activityBtn
                        Layout.preferredWidth: 74
                        Layout.fillWidth: true
                        Layout.maximumWidth: 110
                        Layout.preferredHeight: 38
                        text: "Activity"

                        background: Rectangle {
                            color: activityPanel.visible ? Theme.primaryLight
                                 : (activityBtn.pressed ? Theme.divider
                                 : (activityBtn.hovered ? Theme.backgroundHover
                                 : Theme.backgroundSecondary))
                            radius: Theme.radiusMd
                            border.width: 1
                            border.color: activityPanel.visible ? Theme.primary : Theme.border
                        }

                        contentItem: RowLayout {
                            spacing: 5
                            Rectangle {
                                Layout.alignment: Qt.AlignVCenter
                                width: 7; height: 7; radius: 3.5
                                visible: activityModel && activityModel.busy
                                color: Theme.primary
                                SequentialAnimation on opacity {
                                    running: activityModel && activityModel.busy
                                    loops: Animation.Infinite
                                    NumberAnimation { to: 0.25; duration: 450 }
                                    NumberAnimation { to: 1.0; duration: 450 }
                                }
                            }
                            Text {
                                Layout.fillWidth: true
                                text: activityBtn.text
                                font.pixelSize: Theme.fontSizeSm
                                color: activityPanel.visible ? Theme.primaryText : Theme.textPrimary
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                        }

                        onClicked: activityPanel.visible = !activityPanel.visible
                    }
            }
        }
    }

    // Activity panel. An overlay rather than a layout row, so showing it never
    // reflows the avatar or the buttons underneath.
    Rectangle {
        id: activityPanel
        visible: false
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 72
        height: Math.min(parent.height * 0.55, 260)
        color: Theme.background
        border.width: 1
        border.color: Theme.divider

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Theme.spacingSm
            spacing: Theme.spacingXs

            RowLayout {
                Layout.fillWidth: true
                Text {
                    Layout.fillWidth: true
                    text: (activityModel && activityModel.busy)
                        ? "Activity — " + activityModel.busyCount + " running"
                        : "Activity"
                    font.pixelSize: Theme.fontSizeSm
                    font.weight: Font.Medium
                    color: Theme.textSecondary
                }
                Text {
                    text: "Hide"
                    font.pixelSize: Theme.fontSizeXs
                    color: Theme.primaryText
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: activityPanel.visible = false
                    }
                }
            }

            ListView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                spacing: 2
                model: activityModel ? activityModel.activity : []
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                delegate: Rectangle {
                    width: ListView.view.width
                    height: row.implicitHeight + 8
                    color: modelData.running ? Theme.primaryLight
                         : (modelData.failed ? Theme.errorLight : "transparent")
                    radius: Theme.radiusSm

                    RowLayout {
                        id: row
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.leftMargin: 6
                        anchors.rightMargin: 6
                        spacing: 6

                        Text {
                            text: modelData.running ? "▶" : (modelData.failed ? "✕" : "✓")
                            font.pixelSize: Theme.fontSizeXs
                            color: modelData.running ? Theme.primary
                                 : (modelData.failed ? Theme.error : Theme.success)
                        }
                        Text {
                            text: modelData.tool
                            font.pixelSize: Theme.fontSizeXs
                            font.family: "monospace"
                            color: Theme.textPrimary
                        }
                        Text {
                            Layout.fillWidth: true
                            text: modelData.detail
                            font.pixelSize: Theme.fontSizeXs
                            color: Theme.textPlaceholder
                            elide: Text.ElideRight
                        }
                        Text {
                            text: modelData.took
                            font.pixelSize: Theme.fontSizeXs
                            color: Theme.textPlaceholder
                        }
                    }
                }

                Text {
                    anchors.centerIn: parent
                    visible: parent.count === 0
                    text: "Nothing yet — tool calls will appear here as they run."
                    font.pixelSize: Theme.fontSizeXs
                    color: Theme.textPlaceholder
                }
            }
        }
    }

    function sendText() {
        let text = textInput.text.trim()
        if (text.length > 0 && eventBridge) {
            eventBridge.onSendText(text)
            textInput.text = ""
        }
    }
}
