// Test only: loaded when theme.conf sets testShots to a directory. Steps the screen
// through its states and saves a PNG of each, then quits. Never active when installed.
import QtQuick

Item {
    id: d
    property var ui
    property string dir: ""
    property int step: 0
    readonly property var steps: [
        { at: 2500, name: "idle", act: function() {} },
        { at: 1200, name: "typing", act: function() { d.find("passField").text = "hunter2!" } },
        { at: 700, name: "wrong-password", act: function() { d.ui.rejected() } },
        { at: 900, name: "caps-lock", act: function() { d.ui.status = ""; d.ui.capsOn = true; d.find("passField").text = "abc" } },
        { at: 900, name: "session-menu", act: function() { d.ui.capsOn = false; d.find("sessionMenu").open() } },
        { at: 900, name: "power-armed", act: function() { d.find("sessionMenu").close(); d.ui.power("poweroff"); d.ui.hint = "SHUT DOWN · POWER THE MACHINE OFF · PRESS TWICE" } }
    ]

    function find(name) {
        var stack = [d.ui]
        while (stack.length) {
            var it = stack.pop()
            if (it.objectName === name)
                return it
            for (var i = 0; i < it.children.length; i++)
                stack.push(it.children[i])
        }
        return null
    }

    Timer {
        id: tick
        interval: d.steps[0].at
        running: d.ui !== undefined
        onTriggered: {
            var st = d.steps[d.step]
            d.ui.grabToImage(function(r) {
                r.saveToFile(d.dir + "/" + d.ui.width + "x" + d.ui.height + "-" + st.name + ".png")
                console.log("bromigos-sddm test: saved " + st.name)
                d.step += 1
                if (d.step >= d.steps.length) {
                    Qt.quit()
                    return
                }
                d.steps[d.step].act()
                tick.interval = d.steps[d.step].at
                tick.restart()
            })
        }
    }
}
