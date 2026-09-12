// A custom combo box
import QtQuick
import QtQuick.Controls
import "../theme"

ComboBox {
    id: root

    implicitWidth: 200
    implicitHeight: 36

    // background
    background: Rectangle {
        radius: Theme.radiusSm
        color: root.enabled ? Theme.background : Theme.backgroundSecondary
        border.width: 1
        border.color: root.pressed || root.popup.visible ? Theme.primary : (root.hovered ? Theme.primary : Theme.border)

        Behavior on border.color {
            ColorAnimation { duration: Theme.animationFast }
        }
    }

    // the shown value, taken straight from displayText
    contentItem: Text {
        leftPadding: Theme.spacingMd
        rightPadding: root.indicator.width + Theme.spacingMd
        text: root.displayText
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeSm
        color: root.enabled ? Theme.textPrimary : Theme.textPlaceholder
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    // the drop-down arrow
    indicator: Item {
        x: root.width - width - Theme.spacingSm
        y: (root.height - height) / 2
        width: 24
        height: 24

        Text {
            anchors.centerIn: parent
            text: root.popup.visible ? "▲" : "▼"
            font.pixelSize: 8
            color: Theme.textSecondary
        }
    }

    // the pop-up menu
    popup: Popup {
        y: root.height + 4
        width: root.width
        implicitHeight: contentItem.implicitHeight + 8
        padding: 4

        background: Rectangle {
            color: Theme.background
            radius: Theme.radiusMd

            // the shadow, faked with several layers
            Rectangle {
                z: -1
                anchors.fill: parent
                anchors.margins: -1
                radius: parent.radius + 1
                color: Theme.shadowLight
            }
            Rectangle {
                z: -2
                anchors.fill: parent
                anchors.margins: -3
                radius: parent.radius + 3
                color: Theme.shadowMedium
            }
            Rectangle {
                z: -3
                anchors.fill: parent
                anchors.margins: -6
                radius: parent.radius + 6
                color: Theme.shadowSubtle
            }
        }

        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: root.popup.visible ? root.delegateModel : null
            currentIndex: root.highlightedIndex
            ScrollIndicator.vertical: ScrollIndicator {}
        }
    }

    // the list items
    delegate: ItemDelegate {
        id: delegateItem
        required property int index
        required property var modelData

        width: root.width - 8
        height: 32
        hoverEnabled: true

        background: Rectangle {
            radius: Theme.radiusSm
            color: delegateItem.hovered ? Theme.backgroundHover : "transparent"
        }

        contentItem: Text {
            leftPadding: Theme.spacingSm
            text: root.textRole ? (delegateItem.modelData[root.textRole] ?? delegateItem.modelData) : delegateItem.modelData
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSm
            color: root.currentIndex === delegateItem.index ? Theme.primary : Theme.textPrimary
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
    }
}
