// Avatar switcher: picks the implementation named by style
// Avatar switcher: picks the concrete avatar by `style`.
//
//   "person" -> AvatarPerson.qml  cartoon man (hair, eyes)
//   "woman"  -> AvatarPerson.qml  the same face drawn as a young woman: long dark
//                                 hair, side fringe, lashes, a faint blush
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
        sourceComponent: root.style === "simple" ? simpleFace
                       : root.style === "woman" ? womanFace : personFace
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
        id: womanFace
        AvatarPerson {
            emotion: root.emotion
            mode: root.mode
            level: root.level
            feminine: true
            skinTop: "#FBDDC4"
            skinBottom: "#F2C4A0"
            skinLine: "#D39A78"
            hairColor: "#3E2A22"
            hairShade: "#2B1D18"
            irisColor: "#7A4E36"
            lipColor: "#D4607A"
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
