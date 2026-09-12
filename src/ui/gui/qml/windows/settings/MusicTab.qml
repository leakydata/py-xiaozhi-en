// Music settings page
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

        Text {
            text: "Music Configuration"
            font.pixelSize: Theme.fontSizeXl
            font.weight: Font.DemiBold
            color: Theme.textPrimary
        }

        // API settings
        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingMd

            Text {
                text: "API Settings"
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
                    text: "Search API"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 120
                }
                TextField {
                    id: musicSearchUrlField
                    Layout.fillWidth: true
                    text: settingsModel ? settingsModel.musicSearchUrl : ""
                    // write back as you type; relying on editingFinished alone often fails to save an empty string
                    onTextEdited: if (settingsModel) settingsModel.musicSearchUrl = text
                    onEditingFinished: if (settingsModel) settingsModel.musicSearchUrl = text
                    placeholderText: "Leave empty to use the default Kuwo search API"
                    font.pixelSize: Theme.fontSizeSm
                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: Theme.backgroundSecondary
                        border.color: musicSearchUrlField.activeFocus ? Theme.primary : "transparent"
                    }
                }

                Text {
                    text: "Direct Link API"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 120
                }
                TextField {
                    id: musicUrlApiField
                    Layout.fillWidth: true
                    text: settingsModel ? settingsModel.musicUrlApi : ""
                    onTextEdited: if (settingsModel) settingsModel.musicUrlApi = text
                    onEditingFinished: if (settingsModel) settingsModel.musicUrlApi = text
                    placeholderText: "Leave empty to use the default lx-music-api"
                    font.pixelSize: Theme.fontSizeSm
                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: Theme.backgroundSecondary
                        border.color: musicUrlApiField.activeFocus ? Theme.primary : "transparent"
                    }
                }

                Text {
                    text: "API Key"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 120
                }
                TextField {
                    id: musicUrlApiKeyField
                    Layout.fillWidth: true
                    text: settingsModel ? settingsModel.musicUrlApiKey : ""
                    onTextEdited: if (settingsModel) settingsModel.musicUrlApiKey = text
                    onEditingFinished: if (settingsModel) settingsModel.musicUrlApiKey = text
                    placeholderText: "Leave empty to use the default key"
                    font.pixelSize: Theme.fontSizeSm
                    background: Rectangle {
                        radius: Theme.radiusSm
                        color: Theme.backgroundSecondary
                        border.color: musicUrlApiKeyField.activeFocus ? Theme.primary : "transparent"
                    }
                }
            }

            Text {
                text: "The search API uses Kuwo's official endpoint; the direct-link API resolves playback URLs (requires an API key)"
                font.pixelSize: Theme.fontSizeXs
                color: Theme.textPlaceholder
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
        }

        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: Theme.divider
        }

        // Playback preferences
        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingMd

            Text {
                text: "Playback Preferences"
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
                    text: "Default Quality"
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.textSecondary
                    Layout.preferredWidth: 120
                }
                XComboBox {
                    id: musicQualityCombo
                    Layout.preferredWidth: 150
                    model: ["128k", "320k"]
                    currentIndex: {
                        var q = settingsModel ? settingsModel.musicDefaultQuality : "320k"
                        var idx = ["128k", "320k"].indexOf(q)
                        return idx >= 0 ? idx : 1
                    }
                    onActivated: function(index) {
                        if (settingsModel) settingsModel.musicDefaultQuality = model[index]
                    }
                    font.pixelSize: Theme.fontSizeSm
                }
            }
        }

        Item { Layout.fillHeight: true }
    }
}
