// Faint stars in the den's dark sky, each twinkling on its own slow cycle. Decoration;
// count = 0 turns it off. Positions are fixed per start; animations run on the
// animation timer only (no per-frame script).
import QtQuick

Item {
    id: field
    property int count: 80
    property real unit: 1
    property color colour: "#9cff8a"

    Repeater {
        model: Math.max(0, field.count)
        delegate: Rectangle {
            id: star
            readonly property real big: Math.random()
            x: Math.random() * field.width
            y: Math.random() * field.height
            width: (1.2 + 1.6 * big * big) * field.unit * 1.4
            height: width
            radius: width / 2
            color: field.colour
            SequentialAnimation on opacity {
                loops: Animation.Infinite
                NumberAnimation { to: 0.12; duration: 1 }
                PauseAnimation { duration: Math.random() * 4000 }
                NumberAnimation { to: 0.25 + 0.45 * star.big; duration: 1600 + Math.random() * 2600; easing.type: Easing.InOutSine }
                NumberAnimation { to: 0.08; duration: 1600 + Math.random() * 2600; easing.type: Easing.InOutSine }
            }
        }
    }
}
