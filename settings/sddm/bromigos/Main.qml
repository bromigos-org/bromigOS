// Bromigos login (SDDM, Qt 6). The den behind the burn-in, a terminal-style sign-in,
// phosphor on void: the same screen as the hyprlock lock screen, plus what a login
// needs (user, session, power). No network, no live data, nothing about the operator.
// Elements and how to change them: README.md next to this file.
import QtQuick
import "components"

Rectangle {
    id: root
    width: 2560
    height: 1440
    color: pc.void_

    // ---- palette (bromigos brand kit: brand/palette.json)
    QtObject {
        id: pc
        readonly property color void_: "#000500"
        readonly property color panel: "#ee001300"
        readonly property color guard: "#003b00"
        readonly property color phosphor: "#39ff14"
        readonly property color soft: "#9cff8a"
        readonly property color dim: "#159b09"
        readonly property color amber: "#d4af37"
        readonly property color danger: "#ff766f"
        readonly property color white: "#e8ffe0"
    }

    // one unit = one pixel at 2560x1440; everything scales with the screen's height
    readonly property real s: Math.min(width / 2560, height / 1440)
    readonly property string mono: fontRegular.status === FontLoader.Ready ? fontRegular.name : "monospace"

    FontLoader { id: fontRegular; source: "fonts/GeistMono-Regular.ttf" }
    FontLoader { source: "fonts/GeistMono-Medium.ttf" }
    FontLoader { source: "fonts/GeistMono-SemiBold.ttf" }
    FontLoader { source: "fonts/GeistMono-Bold.ttf" }

    // ---- state
    property int sessionIndex: -1
    property var sessionNames: []
    property var userNames: []
    // the account to sign in as without typing: the last one, or the only one. Its name is
    // never shown (on this desk the account name is the operator's callsign).
    readonly property string knownUser: {
        var last = (typeof userModel !== "undefined" && userModel) ? (userModel.lastUser || "") : ""
        return last !== "" ? last : (userNames.length === 1 ? userNames[0] : "")
    }
    property bool typingUser: false
    property int attempts: 0
    property string status: ""          // "", "verifying", "rejected", "accepted"
    property string infoText: ""
    property string hint: ""            // the hovered or focused control's explanation
    property string armed: ""           // "reboot" | "poweroff" while waiting for a second press
    property bool capsOn: typeof keyboard !== "undefined" && keyboard !== null && keyboard.capsLock === true

    function sessionName(i) {
        return (i >= 0 && i < sessionNames.length) ? sessionNames[i] : "SESSION"
    }

    function chooseSession() {
        if (sessionIndex >= 0)
            return
        var last = (typeof sessionModel !== "undefined" && sessionModel) ? sessionModel.lastIndex : -1
        if (last >= 0 && last < sessionNames.length) {
            sessionIndex = last
            return
        }
        var want = String(config.defaultSession || "Hyprland").toLowerCase()
        for (var i = 0; i < sessionNames.length; i++) {
            if (String(sessionNames[i]).toLowerCase() === want) {
                sessionIndex = i
                return
            }
        }
        sessionIndex = sessionNames.length ? 0 : -1
    }

    function login() {
        if (userField.text.length === 0) {
            userField.forceActiveFocus()
            return
        }
        status = "verifying"
        infoText = ""
        verifyTimer.restart()
        sddm.login(userField.text, passField.text, Math.max(sessionIndex, 0))
    }

    // The login service normally answers in well under a second. If it never does
    // (the greeter's --test-mode has no daemon behind it; a wedged PAM module), don't
    // leave the operator staring at VERIFYING: give the form back and say why.
    function noAnswer() {
        if (status !== "verifying") return
        status = ""
        infoText = "no answer from the login service"
        passField.text = ""
        passField.forceActiveFocus()
    }

    function rejected() {
        attempts += 1
        status = "rejected"
        passField.text = ""
        passField.forceActiveFocus()
        failAnim.restart()
        rejectTimer.restart()
    }

    function power(kind) {
        if (kind === "suspend") {
            sddm.suspend()
            return
        }
        if (armed === kind) {                      // second press within 4 s: do it
            armed = ""
            if (kind === "reboot")
                sddm.reboot()
            else
                sddm.powerOff()
            return
        }
        armed = kind
        armTimer.restart()
    }

    Timer { id: rejectTimer; interval: 2500; onTriggered: if (root.status === "rejected") root.status = "" }
    Timer { id: verifyTimer; interval: 12000; onTriggered: root.noAnswer() }
    Timer { id: armTimer; interval: 4000; onTriggered: root.armed = "" }

    Connections {
        target: sddm
        function onLoginFailed() { verifyTimer.stop(); root.rejected() }
        function onLoginSucceeded() { verifyTimer.stop(); root.status = "accepted" }
        function onInformationMessage(message) { root.infoText = message }
    }

    // session names, read once from the model (a Repeater creates every delegate)
    Item {
        visible: false
        Repeater {
            model: sessionModel
            delegate: Item {
                required property int index
                required property string name
                Component.onCompleted: {
                    var a = root.sessionNames.slice()
                    a[index] = name
                    root.sessionNames = a
                    chooseTimer.restart()
                }
            }
        }
    }
    Timer { id: chooseTimer; interval: 1; onTriggered: root.chooseSession() }

    Item {
        visible: false
        Repeater {
            model: userModel
            delegate: Item {
                required property int index
                required property string name
                Component.onCompleted: {
                    var a = root.userNames.slice()
                    a[index] = name
                    root.userNames = a
                }
            }
        }
    }

    // ---- the den (the lock-screen variant chosen at install; never one with the operator in it)
    Image {
        anchors.fill: parent
        source: config.background || ""
        fillMode: Image.PreserveAspectCrop
        asynchronous: false
        cache: false
        smooth: true
    }

    // faint stars in the den's dark sky (decoration)
    Starfield {
        x: 0
        y: 0
        width: parent.width * 0.42
        height: parent.height * 0.60
        count: parseInt(config.stars || "80")
        unit: root.s
        colour: pc.soft
    }

    // ---- the burn-in: flame holds still, the motto ring turns counter-clockwise
    Item {
        id: emblem
        width: 420 * root.s
        height: width
        anchors.horizontalCenter: parent.horizontalCenter
        y: 440 * root.s - height / 2
        Image {
            id: ring
            anchors.fill: parent
            source: config.ring || ""
            sourceSize.width: 1024
            sourceSize.height: 1024
            smooth: true
            mipmap: true
            RotationAnimator on rotation {
                from: 0
                to: -360
                duration: Math.max(4, parseFloat(config.ringSeconds || "24")) * 1000
                loops: Animation.Infinite
                running: true
            }
        }
        Image {
            anchors.fill: parent
            source: config.flame || ""
            sourceSize.width: 1024
            sourceSize.height: 1024
            smooth: true
            mipmap: true
        }
    }

    Text {
        id: caption
        anchors.horizontalCenter: parent.horizontalCenter
        y: 690 * root.s
        text: config.caption || "TRANSMISSION INTERCEPTED"
        color: pc.phosphor
        font.family: root.mono
        font.weight: Font.Bold
        font.pixelSize: 20 * root.s
        font.letterSpacing: 6 * root.s
    }

    // ---- clock and date
    Text {
        id: clock
        anchors.horizontalCenter: parent.horizontalCenter
        y: 735 * root.s
        color: pc.phosphor
        font.family: root.mono
        font.weight: Font.Bold
        font.pixelSize: 138 * root.s
        text: Qt.formatTime(new Date(), "HH:mm")
    }
    Text {
        id: date
        anchors.horizontalCenter: parent.horizontalCenter
        y: 905 * root.s
        color: pc.soft
        font.family: root.mono
        font.weight: Font.DemiBold
        font.pixelSize: 17 * root.s
        font.letterSpacing: 4 * root.s
        text: Qt.formatDate(new Date(), "dddd dd MMMM yyyy").toUpperCase()
    }
    Timer {
        interval: 1000
        running: true
        repeat: true
        onTriggered: {
            var d = new Date()
            clock.text = Qt.formatTime(d, "HH:mm")
            date.text = Qt.formatDate(d, "dddd dd MMMM yyyy").toUpperCase()
        }
    }

    // ---- sign-in: user, passphrase, status
    Item {
        id: form
        width: 520 * root.s
        height: 190 * root.s
        anchors.horizontalCenter: parent.horizontalCenter
        y: 975 * root.s

        SequentialAnimation {             // a calm shake: three damped swings, then still
            id: failAnim
            NumberAnimation { target: form; property: "anchors.horizontalCenterOffset"; to: -9 * root.s; duration: 70; easing.type: Easing.OutQuad }
            NumberAnimation { target: form; property: "anchors.horizontalCenterOffset"; to: 7 * root.s; duration: 110; easing.type: Easing.InOutQuad }
            NumberAnimation { target: form; property: "anchors.horizontalCenterOffset"; to: -4 * root.s; duration: 110; easing.type: Easing.InOutQuad }
            NumberAnimation { target: form; property: "anchors.horizontalCenterOffset"; to: 0; duration: 140; easing.type: Easing.OutQuad }
        }

        Field {
            id: userField
            width: parent.width
            height: 54 * root.s
            y: 0
            unit: root.s
            family: root.mono
            pal: pc
            placeholder: "USER"
            text: root.knownUser
            cover: (root.knownUser !== "" && !root.typingUser) ? "ACCOUNT ON RECORD" : ""
            about: cover !== "" ? "ACCOUNT · THE LAST ONE SIGNED IN, NAME HIDDEN · SPACE OR CLICK TO SIGN IN AS SOMEONE ELSE"
                                : "USER · THE ACCOUNT TO SIGN IN AS · ENTER OR TAB MOVES TO THE PASSPHRASE"
            onAccepted: passField.forceActiveFocus()
            onUncover: { root.typingUser = true; userField.text = ""; root.hint = "USER · TYPE THE ACCOUNT TO SIGN IN AS" }
            onHovered: function(on) { root.hint = on ? about : "" }
            KeyNavigation.tab: passField
            KeyNavigation.backtab: shutdownBtn
        }

        Field {
            id: passField
            objectName: "passField"
            width: parent.width
            height: 54 * root.s
            y: 66 * root.s
            unit: root.s
            family: root.mono
            pal: pc
            secret: true
            placeholder: "PASSPHRASE"
            failed: root.status === "rejected"
            about: "PASSPHRASE · ENTER SIGNS IN · ESC CLEARS"
            onAccepted: root.login()
            onHovered: function(on) { root.hint = on ? about : "" }
            onTextChanged: if (root.status === "rejected" && text.length) root.status = ""
            KeyNavigation.tab: sessionBtn
            KeyNavigation.backtab: userField
        }

        Text {
            id: statusLine
            anchors.horizontalCenter: parent.horizontalCenter
            y: 138 * root.s
            font.family: root.mono
            font.pixelSize: 15 * root.s
            font.letterSpacing: 3 * root.s
            color: root.status === "rejected" ? pc.danger : (root.status === "verifying" || root.capsOn ? pc.amber : pc.dim)
            text: root.status === "verifying" ? "> VERIFYING"
                : root.status === "accepted" ? "> ACCEPTED"
                : root.status === "rejected" ? "> REJECTED · " + root.attempts
                : root.infoText !== "" ? "> " + root.infoText.toUpperCase()
                : root.capsOn ? "CAPS LOCK IS ON"
                : ""
        }
    }

    // ---- bottom bar: session (left), the hint line and sign-off (centre), power (right)
    SessionButton {
        id: sessionBtn
        x: 60 * root.s
        y: parent.height - 78 * root.s
        unit: root.s
        family: root.mono
        pal: pc
        label: root.sessionName(root.sessionIndex)
        about: "SESSION · WHAT STARTS AFTER SIGN-IN · ENTER OPENS THE LIST"
        onOpen: sessionMenu.open()
        onHovered: function(on) { root.hint = on ? about : "" }
        KeyNavigation.tab: suspendBtn
        KeyNavigation.backtab: passField
    }

    SessionMenu {
        id: sessionMenu
        objectName: "sessionMenu"
        x: sessionBtn.x
        anchors.bottom: sessionBtn.top
        anchors.bottomMargin: 10 * root.s
        unit: root.s
        family: root.mono
        pal: pc
        names: root.sessionNames
        current: root.sessionIndex
        onChosen: function(i) { root.sessionIndex = i; passField.forceActiveFocus() }
        onClosed: sessionBtn.forceActiveFocus()
    }

    Row {
        anchors.right: parent.right
        anchors.rightMargin: 60 * root.s
        y: parent.height - 78 * root.s
        spacing: 18 * root.s

        PowerButton {
            id: suspendBtn
            unit: root.s; family: root.mono; pal: pc
            label: "SUSPEND"
            enabled: sddm.canSuspend
            about: "SUSPEND · SLEEP NOW; WAKING RETURNS TO THIS SCREEN"
            onActivated: root.power("suspend")
            onHovered: function(on) { root.hint = on ? about : "" }
            KeyNavigation.tab: rebootBtn
            KeyNavigation.backtab: sessionBtn
        }
        PowerButton {
            id: rebootBtn
            unit: root.s; family: root.mono; pal: pc
            label: root.armed === "reboot" ? "AGAIN TO REBOOT" : "REBOOT"
            warn: root.armed === "reboot"
            enabled: sddm.canReboot
            about: "REBOOT · RESTART THE MACHINE · PRESS TWICE"
            onActivated: root.power("reboot")
            onHovered: function(on) { root.hint = on ? about : "" }
            KeyNavigation.tab: shutdownBtn
            KeyNavigation.backtab: suspendBtn
        }
        PowerButton {
            id: shutdownBtn
            unit: root.s; family: root.mono; pal: pc
            label: root.armed === "poweroff" ? "AGAIN TO SHUT DOWN" : "SHUT DOWN"
            warn: root.armed === "poweroff"
            enabled: sddm.canPowerOff
            about: "SHUT DOWN · POWER THE MACHINE OFF · PRESS TWICE"
            onActivated: root.power("poweroff")
            onHovered: function(on) { root.hint = on ? about : "" }
            KeyNavigation.tab: userField
            KeyNavigation.backtab: rebootBtn
        }
    }

    Text {
        id: hintLine
        anchors.horizontalCenter: parent.horizontalCenter
        y: parent.height - 92 * root.s
        font.family: root.mono
        font.pixelSize: 13 * root.s
        font.letterSpacing: 2 * root.s
        color: pc.soft
        opacity: root.hint !== "" ? 0.9 : 0.0
        text: root.hint
        Behavior on opacity { NumberAnimation { duration: 160 } }
    }

    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 36 * root.s
        font.family: root.mono
        font.weight: Font.DemiBold
        font.pixelSize: 15 * root.s
        font.letterSpacing: 5 * root.s
        color: Qt.rgba(0.082, 0.608, 0.035, 0.6)
        text: config.signoff || "STILL LIT."
    }

    Timer {                               // after the models have filled in
        interval: 60
        running: true
        onTriggered: {
            if (root.knownUser !== "")
                passField.forceActiveFocus()
            else
                userField.forceActiveFocus()
        }
    }

    // ---- test only: screenshots when theme.conf sets testShots (never in an installed theme)
    Loader {
        active: String(config.testShots || "") !== ""
        source: "components/TestDriver.qml"
        onLoaded: {
            item.ui = root
            item.dir = String(config.testShots)
        }
    }
}
