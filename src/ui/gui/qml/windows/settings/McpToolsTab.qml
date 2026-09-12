// MCP tool enablement: groups + per-tool switches (blacklist MCP_TOOLS.DISABLED)
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../theme"
import "../../controls"

ScrollView {
    id: root
    clip: true
    ScrollBar.vertical.policy: ScrollBar.AlwaysOn
    // leave room for the vertical scrollbar so the right-hand switches are not clipped
    rightPadding: 8
    contentWidth: availableWidth

    property var catalog: []

    function reloadCatalog() {
        if (!settingsModel) {
            catalog = []
            return
        }
        try {
            catalog = JSON.parse(settingsModel.mcpToolsCatalogJson || "[]")
        } catch (e) {
            catalog = []
        }
    }

    function groupsModel() {
        var map = ({})
        var order = []
        for (var i = 0; i < catalog.length; i++) {
            var row = catalog[i]
            var g = row.group || "other"
            if (!map[g]) {
                map[g] = {
                    group: g,
                    groupLabel: row.groupLabel || g,
                    tools: []
                }
                order.push(g)
            }
            map[g].tools.push(row)
        }
        var out = []
        for (var j = 0; j < order.length; j++)
            out.push(map[order[j]])
        return out
    }

    function groupEnabledCount(tools) {
        var n = 0
        for (var i = 0; i < tools.length; i++)
            if (tools[i].enabled)
                n++
        return n
    }

    function groupStatusText(tools) {
        var on = groupEnabledCount(tools)
        var total = tools.length
        // use the count, so it does not duplicate the Enable All / Disable All button text
        return on + "/" + total
    }

    component GroupActionButton: Button {
        id: btn
        font.pixelSize: Theme.fontSizeXs
        Layout.preferredHeight: 28
        Layout.preferredWidth: 52
        padding: 0
        background: Rectangle {
            radius: Theme.radiusSm
            color: btn.pressed ? Theme.backgroundHover
                 : (btn.hovered ? Theme.backgroundSecondary : Theme.background)
            border.width: 1
            border.color: Theme.divider
        }
        contentItem: Text {
            text: btn.text
            font.pixelSize: Theme.fontSizeXs
            color: Theme.textSecondary
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
    }

    Component.onCompleted: reloadCatalog()

    Connections {
        target: settingsModel
        function onSettingsChanged() { root.reloadCatalog() }
    }

    ColumnLayout {
        width: root.availableWidth
        spacing: Theme.spacingLg

        Text {
            text: "MCP Tools"
            font.pixelSize: Theme.fontSizeXl
            font.weight: Font.DemiBold
            color: Theme.textPrimary
        }

        Text {
            Layout.fillWidth: true
            text: "Controls which tools are exposed to the server. Disabled tools do not appear in tools/list and cannot be called. If connected, saving reconnects automatically to refresh the list."
            font.pixelSize: Theme.fontSizeXs
            color: Theme.textSecondary
            wrapMode: Text.WordWrap
        }

        Repeater {
            model: root.groupsModel()

            delegate: ColumnLayout {
                id: groupBlock
                required property var modelData
                Layout.fillWidth: true
                spacing: Theme.spacingSm

                // Group header
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.spacingSm

                    Text {
                        text: groupBlock.modelData.groupLabel
                        font.pixelSize: Theme.fontSizeMd
                        font.weight: Font.Medium
                        color: Theme.textSecondary
                    }

                    Text {
                        text: root.groupStatusText(groupBlock.modelData.tools)
                        font.pixelSize: Theme.fontSizeXs
                        color: Theme.textPlaceholder
                    }

                    Item { Layout.fillWidth: true }

                    GroupActionButton {
                        text: "Enable All"
                        onClicked: {
                            if (settingsModel)
                                settingsModel.setMcpToolGroupEnabled(groupBlock.modelData.group, true)
                        }
                    }
                    GroupActionButton {
                        text: "Disable All"
                        onClicked: {
                            if (settingsModel)
                                settingsModel.setMcpToolGroupEnabled(groupBlock.modelData.group, false)
                        }
                    }
                }

                // Tool list card
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: toolsCol.implicitHeight + Theme.spacingSm * 2
                    radius: Theme.radiusMd
                    color: Theme.backgroundSecondary
                    border.width: 1
                    border.color: Theme.divider

                    ColumnLayout {
                        id: toolsCol
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: Theme.spacingSm
                        spacing: 0

                        Repeater {
                            model: groupBlock.modelData.tools

                            delegate: ColumnLayout {
                                id: toolRow
                                required property var modelData
                                required property int index
                                Layout.fillWidth: true
                                spacing: 0

                                RowLayout {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 48
                                    Layout.leftMargin: Theme.spacingSm
                                    Layout.rightMargin: Theme.spacingSm
                                    spacing: Theme.spacingMd

                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 2

                                        Text {
                                            text: toolRow.modelData.label || toolRow.modelData.name
                                            font.pixelSize: Theme.fontSizeSm
                                            color: Theme.textPrimary
                                            elide: Text.ElideRight
                                            Layout.fillWidth: true
                                        }
                                        Text {
                                            text: toolRow.modelData.name
                                            font.pixelSize: Theme.fontSizeXs
                                            color: Theme.textPlaceholder
                                            elide: Text.ElideMiddle
                                            Layout.fillWidth: true
                                        }
                                    }

                                    // fixed switch area so it cannot be squeezed out or clipped
                                    Item {
                                        Layout.preferredWidth: 52
                                        Layout.preferredHeight: 28
                                        Layout.alignment: Qt.AlignVCenter

                                        XSwitch {
                                            anchors.centerIn: parent
                                            // avoid contentItem taking space when there is no text
                                            text: ""
                                            checked: toolRow.modelData.enabled
                                            onToggled: {
                                                if (settingsModel)
                                                    settingsModel.setMcpToolEnabled(
                                                        toolRow.modelData.name, checked)
                                            }
                                        }
                                    }
                                }

                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.leftMargin: Theme.spacingSm
                                    Layout.rightMargin: Theme.spacingSm
                                    height: 1
                                    color: Theme.divider
                                    visible: toolRow.index < groupBlock.modelData.tools.length - 1
                                }
                            }
                        }
                    }
                }
            }
        }

        Item { Layout.preferredHeight: Theme.spacingMd }
    }
}
