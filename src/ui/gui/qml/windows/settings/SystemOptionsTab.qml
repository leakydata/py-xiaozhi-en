// System options settings page
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
            text: "System Options"
            font.pixelSize: Theme.fontSizeXl
            font.weight: Font.DemiBold
            color: Theme.textPrimary
        }

        // Basic information section
        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingMd

            // Section title
            Text {
                text: "Basic Information"
                font.pixelSize: Theme.fontSizeMd
                font.weight: Font.Medium
                color: Theme.textSecondary
            }

            // Avatar style selection
            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spacingLg

                Text {
                    text: "Avatar"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 100
                }
                XComboBox {
                    id: avatarCombo
                    Layout.preferredWidth: 200
                    // index order must match avatarValues below
                    property var avatarValues: ["person", "woman", "simple", "gif"]
                    model: ["Cartoon man", "Cartoon woman (Xiaozhi)", "Abstract face", "Animated emoji (GIF)"]
                    currentIndex: {
                        if (!settingsModel) return 0
                        var i = avatarValues.indexOf(settingsModel.avatarStyle)
                        return i < 0 ? 0 : i
                    }
                    onActivated: function(index) {
                        if (settingsModel) settingsModel.avatarStyle = avatarValues[index]
                    }
                    font.pixelSize: Theme.fontSizeSm
                }
            }

            Text {
                text: "Cartoon man, Cartoon woman and Abstract face are drawn live and lip-sync to audio. "
                    + "Animated emoji uses the bundled GIF set. Takes effect immediately."
                font.pixelSize: Theme.fontSizeXs
                color: Theme.textPlaceholder
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }

            // Ambient sound awareness
            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spacingLg

                Text {
                    text: "Listen to the room"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 140
                }
                XSwitch {
                    id: ambientSwitch
                    checked: settingsModel ? settingsModel.ambientSoundsEnabled : true
                    onToggled: if (settingsModel) settingsModel.ambientSoundsEnabled = checked
                }
            }

            Text {
                text: "Names the sounds the microphone hears that are not speech (typing, a dog, "
                    + "music, an alarm) and notes when someone is around even if they are not "
                    + "talking, so the assistant can be told. Runs on this computer; applies "
                    + "when you save."
                font.pixelSize: Theme.fontSizeXs
                color: Theme.textPlaceholder
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spacingLg
                opacity: ambientSwitch.checked ? 1 : 0.45

                Text {
                    text: "Speak up"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 140
                }
                XSwitch {
                    enabled: ambientSwitch.checked
                    checked: settingsModel ? settingsModel.ambientSpeakUp : false
                    onToggled: if (settingsModel) settingsModel.ambientSpeakUp = checked
                }
            }

            Text {
                text: "When the room has been quiet for a couple of minutes, she may mention a notable "
                    + "sound on her own (a doorbell, the dog whimpering, an alarm, something breaking), "
                    + "at most once every five minutes."
                font.pixelSize: Theme.fontSizeXs
                color: Theme.textPlaceholder
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spacingLg
                opacity: ambientSwitch.checked ? 1 : 0.45

                Text {
                    text: "Check in"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 140
                }
                XSwitch {
                    enabled: ambientSwitch.checked
                    checked: settingsModel ? settingsModel.ambientCheckIn : false
                    onToggled: if (settingsModel) settingsModel.ambientCheckIn = checked
                }
            }

            Text {
                text: "When the server ends a conversation but the room still sounds like you are "
                    + "there (typing, footsteps, a voice), she reconnects and asks if you want to "
                    + "keep talking instead of going idle. Only once until you answer."
                font.pixelSize: Theme.fontSizeXs
                color: Theme.textPlaceholder
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }

            // Form fields
            GridLayout {
                Layout.fillWidth: true
                columns: 2
                rowSpacing: Theme.spacingMd
                columnSpacing: Theme.spacingLg

                Text {
                    text: "Client ID"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 100
                }
                TextField {
                    id: clientIdField
                    Layout.fillWidth: true
                    text: settingsModel ? settingsModel.clientId : ""
                    onEditingFinished: if (settingsModel) settingsModel.clientId = text
                    placeholderText: "Auto-generated"
                    font.pixelSize: Theme.fontSizeSm
                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: Theme.backgroundSecondary
                        border.color: clientIdField.activeFocus ? Theme.primary : "transparent"
                    }
                }

                Text {
                    text: "Device ID"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 100
                }
                TextField {
                    id: deviceIdField
                    Layout.fillWidth: true
                    text: settingsModel ? settingsModel.deviceId : ""
                    onEditingFinished: if (settingsModel) settingsModel.deviceId = text
                    placeholderText: "Auto-generated"
                    font.pixelSize: Theme.fontSizeSm
                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: Theme.backgroundSecondary
                        border.color: deviceIdField.activeFocus ? Theme.primary : "transparent"
                    }
                }

            }
        }

        // Divider
        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: Theme.divider
        }

        // Natural conversation section
        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingMd

            Text {
                text: "Natural Conversation"
                font.pixelSize: Theme.fontSizeMd
                font.weight: Font.Medium
                color: Theme.textSecondary
            }

            GridLayout {
                Layout.fillWidth: true
                columns: 2
                rowSpacing: Theme.spacingMd
                columnSpacing: Theme.spacingLg

                Text {
                    text: "Enable"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 100
                }
                XSwitch {
                    id: turnTakingSwitch
                    checked: settingsModel ? settingsModel.turnTakingEnabled : false
                    onToggled: if (settingsModel) settingsModel.turnTakingEnabled = checked
                }

                Text {
                    text: "Let Me Interrupt"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 100
                    opacity: turnTakingSwitch.checked ? 1 : 0.45
                }
                XSwitch {
                    enabled: turnTakingSwitch.checked
                    opacity: turnTakingSwitch.checked ? 1 : 0.45
                    checked: settingsModel ? settingsModel.turnTakingInterruptions : true
                    onToggled: if (settingsModel) settingsModel.turnTakingInterruptions = checked
                }

                Text {
                    text: "Listening Sounds"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 100
                    opacity: turnTakingSwitch.checked ? 1 : 0.45
                }
                XSwitch {
                    enabled: turnTakingSwitch.checked
                    opacity: turnTakingSwitch.checked ? 1 : 0.45
                    checked: settingsModel ? settingsModel.turnTakingBackchannels : false
                    onToggled: if (settingsModel) settingsModel.turnTakingBackchannels = checked
                }

                Text {
                    text: "Wait After Unfinished Phrase"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 100
                    opacity: turnTakingSwitch.checked ? 1 : 0.45
                }
                XSpinBox {
                    // tenths of a second, shown as seconds
                    Layout.preferredWidth: 120
                    enabled: turnTakingSwitch.checked
                    opacity: turnTakingSwitch.checked ? 1 : 0.45
                    from: 10
                    to: 80
                    stepSize: 5
                    value: settingsModel ? Math.round(settingsModel.turnTakingIncompleteS * 10) : 30
                    textFromValue: function(v, locale) { return (v / 10).toFixed(1) + " s" }
                    valueFromText: function(t, locale) { return Math.round(parseFloat(t) * 10) }
                    onValueModified: if (settingsModel) settingsModel.turnTakingIncompleteS = value / 10
                    font.pixelSize: Theme.fontSizeSm
                }
            }

            Text {
                Layout.fillWidth: true
                text: "Decides when you've finished from what you said, not just the pause: \"I'm looking for my...\" waits, a finished question gets answered in under a second. With interruptions on, talking over the assistant stops it, but \"yeah\" or \"mm-hm\" don't. Runs on the home server's speech models (Parakeet + pyannote), which take about 30 s to load after switching on; until then, and if they can't load, conversations work exactly as before. Listening sounds: an occasional \"mm-hm\" or \"yeah\" in your pauses, in the assistant's own voice - say \"learn your listening sounds\" to it once to record them. Takes effect when settings are saved."
                font.pixelSize: Theme.fontSizeXs
                color: Theme.textSecondary
                wrapMode: Text.WordWrap
            }
        }

        // Divider
        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: Theme.divider
        }

        // Echo cancellation section
        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingMd

            Text {
                text: "Echo Cancellation"
                font.pixelSize: Theme.fontSizeMd
                font.weight: Font.Medium
                color: Theme.textSecondary
            }

            GridLayout {
                Layout.fillWidth: true
                columns: 2
                rowSpacing: Theme.spacingMd
                columnSpacing: Theme.spacingLg

                Text {
                    text: "Enable"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 100
                }
                XSwitch {
                    id: aecEnabledSwitch
                    checked: settingsModel ? settingsModel.aecEnabled : false
                    onToggled: if (settingsModel) settingsModel.aecEnabled = checked
                }

                Text {
                    text: "Parallel Music Playback"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 100
                    opacity: aecEnabledSwitch.checked ? 1 : 0.45
                }
                XSwitch {
                    enabled: aecEnabledSwitch.checked
                    opacity: aecEnabledSwitch.checked ? 1 : 0.45
                    checked: settingsModel ? settingsModel.aecMusicParallel : true
                    onToggled: if (settingsModel) settingsModel.aecMusicParallel = checked
                }

                Text {
                    text: "Delay Compensation Frames"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 100
                    opacity: aecEnabledSwitch.checked ? 1 : 0.45
                }
                XSpinBox {
                    Layout.preferredWidth: 120
                    enabled: aecEnabledSwitch.checked
                    opacity: aecEnabledSwitch.checked ? 1 : 0.45
                    from: 0
                    to: 20
                    value: settingsModel ? settingsModel.aecFrameDelay : 3
                    onValueModified: if (settingsModel) settingsModel.aecFrameDelay = value
                    font.pixelSize: Theme.fontSizeSm
                }

                Text {
                    text: "Noise Suppression Preprocessing"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 100
                    opacity: aecEnabledSwitch.checked ? 1 : 0.45
                }
                XSwitch {
                    enabled: aecEnabledSwitch.checked
                    opacity: aecEnabledSwitch.checked ? 1 : 0.45
                    checked: settingsModel ? settingsModel.aecEnablePreprocess : true
                    onToggled: if (settingsModel) settingsModel.aecEnablePreprocess = checked
                }
            }

            Text {
                Layout.fillWidth: true
                text: "Cancels echo from this app's TTS/music; enabling it switches to real-time conversation mode. Parallel music = music ducks instead of pausing during TTS. Delay compensation = 40ms + N x protocol frame length; increase it for Bluetooth devices. Takes effect after restart."
                font.pixelSize: Theme.fontSizeXs
                color: Theme.textSecondary
                wrapMode: Text.WordWrap
            }
        }

        // Divider
        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: Theme.divider
        }

        // Network settings section
        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingMd

            Text {
                text: "Network Configuration"
                font.pixelSize: Theme.fontSizeMd
                font.weight: Font.Medium
                color: Theme.textSecondary
            }

            GridLayout {
                Layout.fillWidth: true
                columns: 2
                rowSpacing: Theme.spacingMd
                columnSpacing: Theme.spacingLg

                Text {
                    text: "WebSocket URL"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 100
                }
                TextField {
                    id: wsUrlField
                    Layout.fillWidth: true
                    text: settingsModel ? settingsModel.websocketUrl : ""
                    onEditingFinished: if (settingsModel) settingsModel.websocketUrl = text
                    placeholderText: "wss://..."
                    font.pixelSize: Theme.fontSizeSm
                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: Theme.backgroundSecondary
                        border.color: wsUrlField.activeFocus ? Theme.primary : "transparent"
                    }
                }

                Text {
                    text: "Access Token"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 100
                }
                XTextField {
                    id: wsTokenField
                    Layout.fillWidth: true
                    text: settingsModel ? settingsModel.websocketToken : ""
                    onEditingFinished: if (settingsModel) settingsModel.websocketToken = text
                    isPassword: true
                }

                Text {
                    text: "OTA Version URL"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 100
                }
                TextField {
                    id: otaUrlField
                    Layout.fillWidth: true
                    text: settingsModel ? settingsModel.otaUrl : ""
                    onEditingFinished: if (settingsModel) settingsModel.otaUrl = text
                    font.pixelSize: Theme.fontSizeSm
                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: Theme.backgroundSecondary
                        border.color: otaUrlField.activeFocus ? Theme.primary : "transparent"
                    }
                }

                Text {
                    text: "Authorization URL"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 100
                }
                TextField {
                    id: authUrlField
                    Layout.fillWidth: true
                    text: settingsModel ? settingsModel.authorizationUrl : ""
                    onEditingFinished: if (settingsModel) settingsModel.authorizationUrl = text
                    font.pixelSize: Theme.fontSizeSm
                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: Theme.backgroundSecondary
                        border.color: authUrlField.activeFocus ? Theme.primary : "transparent"
                    }
                }

                Text {
                    text: "Activation Version"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 100
                }
                XComboBox {
                    id: activationCombo
                    Layout.preferredWidth: 120
                    model: ["v1", "v2"]
                    currentIndex: settingsModel && settingsModel.activationVersion === "v2" ? 1 : 0
                    onActivated: function(index) {
                        if (settingsModel) settingsModel.activationVersion = index === 1 ? "v2" : "v1"
                    }
                    font.pixelSize: Theme.fontSizeSm
                }
            }
        }

        // Divider
        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: Theme.divider
        }

        // MQTT settings section
        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingMd

            Text {
                text: "MQTT Configuration"
                font.pixelSize: Theme.fontSizeMd
                font.weight: Font.Medium
                color: Theme.textSecondary
            }

            GridLayout {
                Layout.fillWidth: true
                columns: 2
                rowSpacing: Theme.spacingMd
                columnSpacing: Theme.spacingLg

                Text {
                    text: "Endpoint"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 100
                }
                TextField {
                    id: mqttEndpointField
                    Layout.fillWidth: true
                    text: settingsModel ? settingsModel.mqttEndpoint : ""
                    onEditingFinished: if (settingsModel) settingsModel.mqttEndpoint = text
                    placeholderText: "mqtt.example.com"
                    font.pixelSize: Theme.fontSizeSm
                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: Theme.backgroundSecondary
                        border.color: mqttEndpointField.activeFocus ? Theme.primary : "transparent"
                    }
                }

                Text {
                    text: "Client ID"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 100
                }
                TextField {
                    id: mqttClientIdField
                    Layout.fillWidth: true
                    text: settingsModel ? settingsModel.mqttClientId : ""
                    onEditingFinished: if (settingsModel) settingsModel.mqttClientId = text
                    font.pixelSize: Theme.fontSizeSm
                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: Theme.backgroundSecondary
                        border.color: mqttClientIdField.activeFocus ? Theme.primary : "transparent"
                    }
                }

                Text {
                    text: "Username"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 100
                }
                TextField {
                    id: mqttUsernameField
                    Layout.fillWidth: true
                    text: settingsModel ? settingsModel.mqttUsername : ""
                    onEditingFinished: if (settingsModel) settingsModel.mqttUsername = text
                    font.pixelSize: Theme.fontSizeSm
                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: Theme.backgroundSecondary
                        border.color: mqttUsernameField.activeFocus ? Theme.primary : "transparent"
                    }
                }

                Text {
                    text: "Password"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 100
                }
                XTextField {
                    id: mqttPasswordField
                    Layout.fillWidth: true
                    text: settingsModel ? settingsModel.mqttPassword : ""
                    onEditingFinished: if (settingsModel) settingsModel.mqttPassword = text
                    isPassword: true
                }

                Text {
                    text: "Publish Topic"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 100
                }
                TextField {
                    id: mqttPubField
                    Layout.fillWidth: true
                    text: settingsModel ? settingsModel.mqttPublishTopic : ""
                    onEditingFinished: if (settingsModel) settingsModel.mqttPublishTopic = text
                    font.pixelSize: Theme.fontSizeSm
                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: Theme.backgroundSecondary
                        border.color: mqttPubField.activeFocus ? Theme.primary : "transparent"
                    }
                }

                Text {
                    text: "Subscribe Topic"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 100
                }
                TextField {
                    id: mqttSubField
                    Layout.fillWidth: true
                    text: settingsModel ? settingsModel.mqttSubscribeTopic : ""
                    onEditingFinished: if (settingsModel) settingsModel.mqttSubscribeTopic = text
                    font.pixelSize: Theme.fontSizeSm
                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: Theme.backgroundSecondary
                        border.color: mqttSubField.activeFocus ? Theme.primary : "transparent"
                    }
                }
            }
        }

        // Divider
        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: Theme.divider
        }

        // Writable directories (cache / logs / music etc.)
        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingMd

            Text {
                text: "Data Directory"
                font.pixelSize: Theme.fontSizeMd
                font.weight: Font.Medium
                color: Theme.textSecondary
            }

            Text {
                Layout.fillWidth: true
                text: "Config files stay in the user data directory. Click 'Browse' to open the system folder dialog; 'Default' clears the field back to the system default. After saving, files are copied from the old directory to the new path on next start."
                font.pixelSize: Theme.fontSizeXs
                color: Theme.textSecondary
                wrapMode: Text.WordWrap
            }

            // Cache
            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spacingSm
                Text {
                    text: "Cache Directory"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 100
                }
                TextField {
                    id: pathCacheField
                    Layout.fillWidth: true
                    text: settingsModel ? settingsModel.pathCacheDir : ""
                    onTextEdited: if (settingsModel) settingsModel.pathCacheDir = text
                    onEditingFinished: if (settingsModel) settingsModel.pathCacheDir = text
                    placeholderText: settingsModel ? settingsModel.pathDefaultCacheDir : ""
                    font.pixelSize: Theme.fontSizeSm
                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: Theme.backgroundSecondary
                        border.color: pathCacheField.activeFocus ? Theme.primary : "transparent"
                    }
                }
                Button {
                    text: "Browse"
                    font.pixelSize: Theme.fontSizeSm
                    Layout.preferredWidth: 64
                    Layout.preferredHeight: 32
                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: parent.pressed ? Theme.backgroundHover : Theme.backgroundSecondary
                        border.width: 1
                        border.color: Theme.divider
                    }
                    contentItem: Text {
                        text: parent.text
                        font.pixelSize: Theme.fontSizeSm
                        color: Theme.textPrimary
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        if (!settingsModel) return
                        var p = settingsModel.browseDirectory("cache")
                        if (p) pathCacheField.text = p
                    }
                }
                Button {
                    text: "Default"
                    font.pixelSize: Theme.fontSizeSm
                    Layout.preferredWidth: 64
                    Layout.preferredHeight: 32
                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: parent.pressed ? Theme.backgroundHover : Theme.backgroundSecondary
                        border.width: 1
                        border.color: Theme.divider
                    }
                    contentItem: Text {
                        text: parent.text
                        font.pixelSize: Theme.fontSizeSm
                        color: Theme.textPrimary
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        if (!settingsModel) return
                        settingsModel.clearPathDir("cache")
                        pathCacheField.text = ""
                    }
                }
            }

            // Log
            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spacingSm
                Text {
                    text: "Log Directory"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 100
                }
                TextField {
                    id: pathLogField
                    Layout.fillWidth: true
                    text: settingsModel ? settingsModel.pathLogDir : ""
                    onTextEdited: if (settingsModel) settingsModel.pathLogDir = text
                    onEditingFinished: if (settingsModel) settingsModel.pathLogDir = text
                    placeholderText: settingsModel ? settingsModel.pathDefaultLogDir : ""
                    font.pixelSize: Theme.fontSizeSm
                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: Theme.backgroundSecondary
                        border.color: pathLogField.activeFocus ? Theme.primary : "transparent"
                    }
                }
                Button {
                    text: "Browse"
                    font.pixelSize: Theme.fontSizeSm
                    Layout.preferredWidth: 64
                    Layout.preferredHeight: 32
                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: parent.pressed ? Theme.backgroundHover : Theme.backgroundSecondary
                        border.width: 1
                        border.color: Theme.divider
                    }
                    contentItem: Text {
                        text: parent.text
                        font.pixelSize: Theme.fontSizeSm
                        color: Theme.textPrimary
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        if (!settingsModel) return
                        var p = settingsModel.browseDirectory("log")
                        if (p) pathLogField.text = p
                    }
                }
                Button {
                    text: "Default"
                    font.pixelSize: Theme.fontSizeSm
                    Layout.preferredWidth: 64
                    Layout.preferredHeight: 32
                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: parent.pressed ? Theme.backgroundHover : Theme.backgroundSecondary
                        border.width: 1
                        border.color: Theme.divider
                    }
                    contentItem: Text {
                        text: parent.text
                        font.pixelSize: Theme.fontSizeSm
                        color: Theme.textPrimary
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        if (!settingsModel) return
                        settingsModel.clearPathDir("log")
                        pathLogField.text = ""
                    }
                }
            }

            // Music
            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spacingSm
                Text {
                    text: "Music Cache"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 100
                }
                TextField {
                    id: pathMusicField
                    Layout.fillWidth: true
                    text: settingsModel ? settingsModel.pathMusicCacheDir : ""
                    onTextEdited: if (settingsModel) settingsModel.pathMusicCacheDir = text
                    onEditingFinished: if (settingsModel) settingsModel.pathMusicCacheDir = text
                    placeholderText: settingsModel ? settingsModel.pathDefaultMusicCacheDir : ""
                    font.pixelSize: Theme.fontSizeSm
                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: Theme.backgroundSecondary
                        border.color: pathMusicField.activeFocus ? Theme.primary : "transparent"
                    }
                }
                Button {
                    text: "Browse"
                    font.pixelSize: Theme.fontSizeSm
                    Layout.preferredWidth: 64
                    Layout.preferredHeight: 32
                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: parent.pressed ? Theme.backgroundHover : Theme.backgroundSecondary
                        border.width: 1
                        border.color: Theme.divider
                    }
                    contentItem: Text {
                        text: parent.text
                        font.pixelSize: Theme.fontSizeSm
                        color: Theme.textPrimary
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        if (!settingsModel) return
                        var p = settingsModel.browseDirectory("music")
                        if (p) pathMusicField.text = p
                    }
                }
                Button {
                    text: "Default"
                    font.pixelSize: Theme.fontSizeSm
                    Layout.preferredWidth: 64
                    Layout.preferredHeight: 32
                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: parent.pressed ? Theme.backgroundHover : Theme.backgroundSecondary
                        border.width: 1
                        border.color: Theme.divider
                    }
                    contentItem: Text {
                        text: parent.text
                        font.pixelSize: Theme.fontSizeSm
                        color: Theme.textPrimary
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        if (!settingsModel) return
                        settingsModel.clearPathDir("music")
                        pathMusicField.text = ""
                    }
                }
            }

            // Wake word
            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spacingSm
                Text {
                    text: "Wake Word Directory"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 100
                }
                TextField {
                    id: pathKeywordsField
                    Layout.fillWidth: true
                    text: settingsModel ? settingsModel.pathKeywordsDir : ""
                    onTextEdited: if (settingsModel) settingsModel.pathKeywordsDir = text
                    onEditingFinished: if (settingsModel) settingsModel.pathKeywordsDir = text
                    placeholderText: settingsModel ? settingsModel.pathDefaultKeywordsDir : ""
                    font.pixelSize: Theme.fontSizeSm
                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: Theme.backgroundSecondary
                        border.color: pathKeywordsField.activeFocus ? Theme.primary : "transparent"
                    }
                }
                Button {
                    text: "Browse"
                    font.pixelSize: Theme.fontSizeSm
                    Layout.preferredWidth: 64
                    Layout.preferredHeight: 32
                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: parent.pressed ? Theme.backgroundHover : Theme.backgroundSecondary
                        border.width: 1
                        border.color: Theme.divider
                    }
                    contentItem: Text {
                        text: parent.text
                        font.pixelSize: Theme.fontSizeSm
                        color: Theme.textPrimary
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        if (!settingsModel) return
                        var p = settingsModel.browseDirectory("keywords")
                        if (p) pathKeywordsField.text = p
                    }
                }
                Button {
                    text: "Default"
                    font.pixelSize: Theme.fontSizeSm
                    Layout.preferredWidth: 64
                    Layout.preferredHeight: 32
                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: parent.pressed ? Theme.backgroundHover : Theme.backgroundSecondary
                        border.width: 1
                        border.color: Theme.divider
                    }
                    contentItem: Text {
                        text: parent.text
                        font.pixelSize: Theme.fontSizeSm
                        color: Theme.textPrimary
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        if (!settingsModel) return
                        settingsModel.clearPathDir("keywords")
                        pathKeywordsField.text = ""
                    }
                }
            }

            // MCP plugins
            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spacingSm
                Text {
                    text: "MCP Plugin Directory"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 100
                }
                TextField {
                    id: pathMcpField
                    Layout.fillWidth: true
                    text: settingsModel ? settingsModel.pathMcpPluginsDir : ""
                    onTextEdited: if (settingsModel) settingsModel.pathMcpPluginsDir = text
                    onEditingFinished: if (settingsModel) settingsModel.pathMcpPluginsDir = text
                    placeholderText: settingsModel ? settingsModel.pathDefaultMcpPluginsDir : ""
                    font.pixelSize: Theme.fontSizeSm
                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: Theme.backgroundSecondary
                        border.color: pathMcpField.activeFocus ? Theme.primary : "transparent"
                    }
                }
                Button {
                    text: "Browse"
                    font.pixelSize: Theme.fontSizeSm
                    Layout.preferredWidth: 64
                    Layout.preferredHeight: 32
                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: parent.pressed ? Theme.backgroundHover : Theme.backgroundSecondary
                        border.width: 1
                        border.color: Theme.divider
                    }
                    contentItem: Text {
                        text: parent.text
                        font.pixelSize: Theme.fontSizeSm
                        color: Theme.textPrimary
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        if (!settingsModel) return
                        var p = settingsModel.browseDirectory("mcp")
                        if (p) pathMcpField.text = p
                    }
                }
                Button {
                    text: "Default"
                    font.pixelSize: Theme.fontSizeSm
                    Layout.preferredWidth: 64
                    Layout.preferredHeight: 32
                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: parent.pressed ? Theme.backgroundHover : Theme.backgroundSecondary
                        border.width: 1
                        border.color: Theme.divider
                    }
                    contentItem: Text {
                        text: parent.text
                        font.pixelSize: Theme.fontSizeSm
                        color: Theme.textPrimary
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        if (!settingsModel) return
                        settingsModel.clearPathDir("mcp")
                        pathMcpField.text = ""
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                text: settingsModel ? settingsModel.pathHints : ""
                font.pixelSize: Theme.fontSizeXs
                color: Theme.textSecondary
                wrapMode: Text.WordWrap
            }
        }

        Item { Layout.fillHeight: true }
    }
}
