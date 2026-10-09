// The session chooser's button: "SESSION · HYPRLAND ▴". Click, Enter or Space opens the list.
import QtQuick

FocusScope {
    id: b
    property string label: ""
    property string about: ""
    property real unit: 1
    property string family: "monospace"
    property var pal
    signal open()
    signal hovered(bool on)
    width: row.width + 28 * unit
    height: 40 * unit
    activeFocusOnTab: true

    Rectangle {
        anchors.fill: parent
        color: b.pal.panel
        border.width: 1
        border.color: b.activeFocus || mouse.containsMouse ? b.pal.phosphor : b.pal.guard
    }
    Row {
        id: row
        anchors.centerIn: parent
        spacing: 10 * b.unit
        Text {
            text: "SESSION"
            color: b.pal.dim
            font.family: b.family
            font.pixelSize: 13 * b.unit
            font.letterSpacing: 3 * b.unit
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            text: b.label.toUpperCase() + "  ▴"
            color: b.activeFocus || mouse.containsMouse ? b.pal.white : b.pal.soft
            font.family: b.family
            font.pixelSize: 15 * b.unit
            font.letterSpacing: 2 * b.unit
            anchors.verticalCenter: parent.verticalCenter
        }
    }
    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onEntered: b.hovered(true)
        onExited: b.hovered(false)
        onClicked: b.open()
    }
    Keys.onReturnPressed: b.open()
    Keys.onEnterPressed: b.open()
    Keys.onSpacePressed: b.open()
    onActiveFocusChanged: b.hovered(activeFocus)
}
