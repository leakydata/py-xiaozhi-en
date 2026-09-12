// Avatar switcher: picks the implementation named by style
// Avatar switcher: picks the concrete avatar by `style`.
//
//   "person" -> AvatarPerson.qml  cartoon person (hair, eyes, stubble)
//   "simple" -> AvatarSimple.qml  abstract coloured disc
//
// Both implementations take the same inputs (emotion / mode / level), so callers
// only ever set `style` and the rest carries over unchanged.
import QtQuick

Item {
    id: root

    property string emotion: "neutral"
    property string mode: "idle"
    property real level: 0.0
    property string style: "person"

    implicitWidth: 220
    implicitHeight: 220

    Loader {
        anchors.fill: parent
        sourceComponent: root.style === "simple" ? simpleFace : personFace
    }

    Component {
        id: personFace
        AvatarPerson {
            emotion: root.emotion
            mode: root.mode
            level: root.level
        }
    }

    Component {
        id: simpleFace
        AvatarSimple {
            emotion: root.emotion
            mode: root.mode
            level: root.level
        }
    }
}
