// Wake word settings page
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
            text: "Wake Word Settings"
            font.pixelSize: Theme.fontSizeXl
            font.weight: Font.DemiBold
            color: Theme.textPrimary
        }

        // Wake word settings
        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingMd

            Text {
                text: "Wake Word"
                font.pixelSize: Theme.fontSizeMd
                font.weight: Font.Medium
                color: Theme.textSecondary
            }

            // Enable wake word
            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spacingMd

                Text {
                    text: "Enable Wake Word"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                }

                Item { Layout.fillWidth: true }

                XSwitch {
                    checked: settingsModel ? settingsModel.wakeWordEnabled : false
                    onToggled: if (settingsModel) settingsModel.wakeWordEnabled = checked
                }
            }

            Rectangle {
                Layout.fillWidth: true
                height: 1
                color: Theme.divider
            }

            // Wake word input
            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spacingMd

                Text {
                    text: "Wake Word"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 80
                }

                TextField {
                    id: wakeWordInput
                    Layout.fillWidth: true
                    text: settingsModel ? settingsModel.wakeWord : ""
                    onTextChanged: if (settingsModel && text !== settingsModel.wakeWord) settingsModel.wakeWord = text
                    placeholderText: "Enter a wake word, e.g. 'Xiaozhi' or 'Hey Jarvis'"
                    font.pixelSize: Theme.fontSizeSm
                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: Theme.backgroundSecondary
                        border.color: wakeWordInput.activeFocus ? Theme.primary : "transparent"
                    }
                }

                // Language label
                Rectangle {
                    visible: settingsModel && settingsModel.wakeWord && settingsModel.wakeWord.length > 0
                    width: langLabel.width + 16
                    height: 24
                    radius: Theme.radiusSm
                    color: settingsModel && settingsModel.wakeWordLang === "zh" ? Theme.primaryLight : Theme.successLight

                    Text {
                        id: langLabel
                        anchors.centerIn: parent
                        text: settingsModel && settingsModel.wakeWordLang === "zh" ? "Chinese" : "English"
                        font.pixelSize: Theme.fontSizeXs
                        color: settingsModel && settingsModel.wakeWordLang === "zh" ? Theme.primary : Theme.success
                    }
                }
            }

            // Preview area
            Rectangle {
                Layout.fillWidth: true
                height: previewLayout.height + 20
                color: Theme.backgroundSecondary
                radius: Theme.radiusSm
                visible: settingsModel && settingsModel.wakeWordPreview && settingsModel.wakeWordPreview.length > 0

                ColumnLayout {
                    id: previewLayout
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.margins: Theme.spacingMd
                    spacing: Theme.spacingXs

                    Text {
                        text: "Conversion Preview"
                        font.pixelSize: Theme.fontSizeXs
                        color: Theme.textPlaceholder
                    }

                    Text {
                        Layout.fillWidth: true
                        text: settingsModel ? settingsModel.wakeWordPreview : ""
                        font.pixelSize: Theme.fontSizeSm
                        color: Theme.textPrimary
                        wrapMode: Text.WrapAnywhere
                    }
                }
            }

            // Save button
            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spacingMd

                Item { Layout.fillWidth: true }

                Button {
                    text: "Save Wake Word"
                    implicitHeight: 36
                    implicitWidth: 120

                    contentItem: Text {
                        text: parent.text
                        font.pixelSize: Theme.fontSizeSm
                        color: "white"
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }

                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: parent.enabled ? (parent.pressed ? Theme.primaryPressed : (parent.hovered ? Theme.primaryHover : Theme.primary)) : Theme.textPlaceholder
                    }

                    enabled: settingsModel && settingsModel.wakeWord && settingsModel.wakeWord.length > 0
                    onClicked: if (settingsModel) settingsModel.saveWakeWord()
                }
            }
        }

        // Divider
        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: Theme.divider
        }

        // Detection parameters
        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingMd

            Text {
                text: "Detection Parameters"
                font.pixelSize: Theme.fontSizeMd
                font.weight: Font.Medium
                color: Theme.textSecondary
            }

            GridLayout {
                Layout.fillWidth: true
                columns: 3
                rowSpacing: Theme.spacingMd
                columnSpacing: Theme.spacingMd

                // Threads
                Text {
                    text: "Threads"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 80
                }

                XSpinBox {
                    Layout.preferredWidth: 120
                    from: 1
                    to: 16
                    value: settingsModel ? settingsModel.numThreads : 4
                    onValueModified: if (settingsModel) settingsModel.numThreads = value
                    font.pixelSize: Theme.fontSizeSm
                }

                Text {
                    text: "Recommended: number of CPU cores"
                    font.pixelSize: Theme.fontSizeXs
                    color: Theme.textPlaceholder
                }

                // Keyword score
                Text {
                    text: "Keyword Score"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 80
                }

                Slider {
                    id: scoreSlider
                    Layout.fillWidth: true
                    from: 0.5
                    to: 3.0
                    stepSize: 0.1
                    value: settingsModel ? settingsModel.keywordsScore : 1.0
                    onMoved: if (settingsModel) settingsModel.keywordsScore = value
                }

                Text {
                    text: scoreSlider.value.toFixed(1)
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textPrimary
                    Layout.preferredWidth: 40
                }

                // Keyword threshold
                Text {
                    text: "Keyword Threshold"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 80
                }

                Slider {
                    id: thresholdSlider
                    Layout.fillWidth: true
                    from: 0.0
                    to: 1.0
                    stepSize: 0.05
                    value: settingsModel ? settingsModel.keywordsThreshold : 0.5
                    onMoved: if (settingsModel) settingsModel.keywordsThreshold = value
                }

                Text {
                    text: thresholdSlider.value.toFixed(2)
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textPrimary
                    Layout.preferredWidth: 40
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
            text: "Supports Chinese and English wake words. Chinese is converted to pinyin automatically; English uses BPE tokenization. A higher score is stricter; a lower threshold is more sensitive."
            font.pixelSize: Theme.fontSizeSm
            color: Theme.textPlaceholder
            wrapMode: Text.WordWrap
        }

        Item { Layout.fillHeight: true }
    }
}
