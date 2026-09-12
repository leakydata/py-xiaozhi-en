// Base class for a frameless, resizable window
import QtQuick
import QtQuick.Window
import Qt5Compat.GraphicalEffects
import "../theme"

Window {
    id: root

    flags: Qt.FramelessWindowHint | Qt.Window
    color: "transparent"

    minimumWidth: 480
    minimumHeight: 360

    // how wide the drag-to-resize edge is
    property int resizeMargin: 8

    // whether it is maximised or fullscreen
    property bool isMaximized: root.visibility === Window.Maximized || root.visibility === Window.FullScreen

    // content area
    default property alias content: contentArea.data

    // keep the theme's window width up to date
    onWidthChanged: Theme.windowWidth = width

    // the main container (rounded, with a border)
    Rectangle {
        id: container
        anchors.fill: parent
        anchors.margins: root.isMaximized ? 0 : 1
        radius: root.isMaximized ? 0 : Theme.windowRadius
        color: Theme.background
        antialiasing: true
        border.width: root.isMaximized ? 0 : 1
        border.color: Theme.border

        // a layer does the rounded-corner clipping
        layer.enabled: !root.isMaximized
        layer.effect: OpacityMask {
            maskSource: Rectangle {
                width: container.width
                height: container.height
                radius: container.radius
            }
        }

        // content area
        Item {
            id: contentArea
            anchors.fill: parent
        }
    }

    // the resize MouseAreas sit on top, and are hidden when maximised
    // left edge
    MouseArea {
        visible: !root.isMaximized
        width: resizeMargin
        height: parent.height - resizeMargin * 2
        x: 0
        y: resizeMargin
        cursorShape: Qt.SizeHorCursor
        onPressed: root.startSystemResize(Qt.LeftEdge)
    }

    // right edge
    MouseArea {
        visible: !root.isMaximized
        width: resizeMargin
        height: parent.height - resizeMargin * 2
        x: parent.width - resizeMargin
        y: resizeMargin
        cursorShape: Qt.SizeHorCursor
        onPressed: root.startSystemResize(Qt.RightEdge)
    }

    // top edge
    MouseArea {
        visible: !root.isMaximized
        width: parent.width - resizeMargin * 2
        height: resizeMargin
        x: resizeMargin
        y: 0
        cursorShape: Qt.SizeVerCursor
        onPressed: root.startSystemResize(Qt.TopEdge)
    }

    // bottom edge
    MouseArea {
        visible: !root.isMaximized
        width: parent.width - resizeMargin * 2
        height: resizeMargin
        x: resizeMargin
        y: parent.height - resizeMargin
        cursorShape: Qt.SizeVerCursor
        onPressed: root.startSystemResize(Qt.BottomEdge)
    }

    // top-left corner
    MouseArea {
        visible: !root.isMaximized
        width: resizeMargin
        height: resizeMargin
        x: 0
        y: 0
        cursorShape: Qt.SizeFDiagCursor
        onPressed: root.startSystemResize(Qt.LeftEdge | Qt.TopEdge)
    }

    // top-right corner
    MouseArea {
        visible: !root.isMaximized
        width: resizeMargin
        height: resizeMargin
        x: parent.width - resizeMargin
        y: 0
        cursorShape: Qt.SizeBDiagCursor
        onPressed: root.startSystemResize(Qt.RightEdge | Qt.TopEdge)
    }

    // bottom-left corner
    MouseArea {
        visible: !root.isMaximized
        width: resizeMargin
        height: resizeMargin
        x: 0
        y: parent.height - resizeMargin
        cursorShape: Qt.SizeBDiagCursor
        onPressed: root.startSystemResize(Qt.LeftEdge | Qt.BottomEdge)
    }

    // bottom-right corner
    MouseArea {
        visible: !root.isMaximized
        width: resizeMargin
        height: resizeMargin
        x: parent.width - resizeMargin
        y: parent.height - resizeMargin
        cursorShape: Qt.SizeFDiagCursor
        onPressed: root.startSystemResize(Qt.RightEdge | Qt.BottomEdge)
    }
}
