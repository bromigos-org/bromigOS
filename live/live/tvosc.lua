-- Den TV's own mpv controller. It is loaded explicitly by tvfull.py, never globally.
-- SPDX-License-Identifier: MIT OR Apache-2.0
local mp = require("mp")
local utils = require("mp.utils")
local assdraw = require("mp.assdraw")
local options = require("mp.options")
local opt = {screen="big", palette=""}
options.read_options(opt, "bromigos-tv")
local overlay = mp.create_osd_overlay("ass-events")
local colors = {}
local x, y, w, h = -1, -1, 1280, 720
local shown_at, expanded, dragging, menu = 0, false, nil, nil
local buttons, menu_rows = {}, {}
local draw, pointer, click

local function bgr(role)
    local c = assert(colors[role] or colors.phosphor, "Den TV palette is missing")
    return c:sub(5,6) .. c:sub(3,4) .. c:sub(1,2)
end
local function safe(text)
    return tostring(text):gsub("\\", "\\e"):gsub("{", "\\{"):gsub("}", "\\}"):gsub("\n", " ")
end
local function clamp(v, a, b) return math.max(a, math.min(b, v)) end
local function inside(r) return r and x >= r[1] and y >= r[2] and x <= r[1]+r[3] and y <= r[2]+r[4] end
local function property(name, fallback) return mp.get_property_native(name) or fallback end
local function action(verb)
    mp.command_native_async({name="subprocess", args={"bromigos-live", "tv", verb, "--screen", opt.screen},
                             playback_only=false, capture_stdout=true, capture_stderr=true}, function() end)
end
local function volume(v)
    mp.set_property_number("volume", clamp(v, 0, 100))
    if v > 0 then mp.set_property_bool("mute", false) end
end
local function volume_at() volume((h-112-y)/150*100) end
local function seek_at() mp.commandv("seek", clamp((x-28)/(w-56), 0, 1)*property("duration", 0), "absolute+exact") end
local function state()
    mp.set_property_native("user-data/den/controller", {loaded=true, expanded=expanded, screen=opt.screen,
        palette=colors, dragging=dragging or false, menu=menu or false})
end
local function rectangle(a, rx, ry, rw, rh, role, opacity)
    a:new_event(); a:append(string.format("{\\an7\\pos(0,0)\\bord0\\shad0\\1c&H%s&\\alpha&H%s&}",
        bgr(role), opacity or "00")); a:draw_start(); a:rect_cw(rx, ry, rx+rw, ry+rh); a:draw_stop()
end
local function text(a, tx, ty, value, size, role, align)
    a:new_event(); a:append(string.format("{\\an%d\\pos(%.1f,%.1f)\\fnGeist Mono\\fs%d\\bord0\\shad0\\1c&H%s&}%s",
        align or 7, tx, ty, size, bgr(role or "soft"), safe(value)))
end
local function button(a, rx, ry, rw, label, cb, tip)
    local r={rx,ry,rw,34}; buttons[#buttons+1]={r=r,cb=cb,tip=tip}
    rectangle(a,rx,ry,rw,34,inside(r) and "phosphor" or "panel",inside(r) and "60" or "10")
    text(a,rx+rw/2,ry+7,label,15,"soft",8)
end
local function track_menu(kind)
    menu=kind; shown_at=mp.get_time(); draw()
end
draw = function()
    local dw,dh = mp.get_osd_size()
    if dw and dw > 0 and dh > 0 then w,h=dw,dh end
    buttons, menu_rows = {}, {}
    local visible = dragging or menu or expanded or property("pause", false) or mp.get_time()-shown_at < 3
    if not visible then overlay:remove(); state(); return end
    local a=assdraw.ass_new()
    rectangle(a,0,h-100,w,100,"panel","20")
    text(a,28,h-94,property("media-title","Den TV"),17,"soft")
    local pos,dur=property("time-pos",0),property("duration",0)
    rectangle(a,28,h-65,w-56,5,"dim")
    rectangle(a,28,h-65,(w-56)*clamp(dur>0 and pos/dur or 0,0,1),5,"phosphor")
    local function clock(v) return string.format("%02d:%02d",math.floor(v/60),math.floor(v%60)) end
    text(a,w-28,h-94,clock(pos).." / "..clock(dur),15,"soft",9)
    button(a,28,h-44,54,property("pause",false) and "PLAY" or "||",function() mp.commandv("cycle","pause") end,"Play or pause")
    button(a,90,h-44,62,"CH -",function() action("prev") end,"Previous channel")
    button(a,160,h-44,62,"CH +",function() action("next") end,"Next channel")
    button(a,230,h-44,80,"SKIP",function() action("skip") end,"Next item on this channel")
    button(a,318,h-44,64,"AUDIO",function() track_menu("audio") end,"Choose audio track")
    button(a,390,h-44,62,"SUBS",function() track_menu("sub") end,"Choose subtitles")
    local vol=property("volume",60)
    local vx=w-240
    button(a,vx,h-44,80,property("mute",false) and "MUTE" or "VOL",function() mp.commandv("cycle","mute") end,"Hover for volume; wheel changes it; click mutes")
    text(a,vx+90,h-36,string.format("%d%%",vol),15,"soft")
    button(a,w-116,h-44,100,"BACK",function() mp.commandv("quit") end,"Back to the den")
    local vr={vx-4,h-284,88,284}
    expanded=inside(vr) or dragging=="volume"
    if expanded then
        rectangle(a,vx-4,h-284,88,235,"panel","08")
        rectangle(a,vx+34,h-262,12,150,"dim")
        rectangle(a,vx+34,h-112-150*vol/100,12,150*vol/100,"phosphor")
        rectangle(a,vx+25,h-116-150*vol/100,30,8,"soft")
        text(a,vx+40,h-278,string.format("%d%%",vol),15,"soft",8)
    end
    local hovered
    for _,b in ipairs(buttons) do if inside(b.r) then hovered=b.tip end end
    if inside({28,h-72,w-56,18}) then
        hovered=clock(clamp((x-28)/(w-56),0,1)*dur).." · Click or drag to seek"
    end
    if hovered then text(a,28,h-128,hovered,14,"phosphor") end
    if menu then
        rectangle(a,318,h-318,340,205,"panel","05")
        text(a,330,h-310,"Choose "..menu.." · click outside to close",14,"phosphor")
        local rows={{id="no",title="Off",type=menu}}
        for _,t in ipairs(property("track-list",{})) do if t.type==menu then rows[#rows+1]=t end end
        for i,t in ipairs(rows) do
            if i>6 then break end
            local r={330,h-286+(i-1)*27,316,24}
            menu_rows[#menu_rows+1]={r=r,id=t.id}
            if inside(r) then rectangle(a,r[1],r[2],r[3],r[4],"phosphor","A0") end
            text(a,r[1]+6,r[2]+3,(t.selected and "* " or "  ")..(t.title or t.lang or tostring(t.id)),14,"soft")
        end
    end
    overlay.res_x=w; overlay.res_y=h; overlay.data=a.text; overlay:update(); state()
end
pointer = function(nx,ny)
    x,y=nx,ny; shown_at=mp.get_time()
    if dragging=="volume" then volume_at() elseif dragging=="seek" then seek_at() end
    draw()
end
click = function(ev)
    if ev.event=="up" then dragging=nil; draw(); return end
    if ev.event~="down" and ev.event~="press" then return end
    shown_at=mp.get_time()
    if menu then
        for _,r in ipairs(menu_rows) do
            if inside(r.r) then mp.set_property(menu=="audio" and "aid" or "sid",r.id); menu=nil; draw(); return end
        end
        menu=nil; draw(); return
    end
    if expanded and inside({w-240,h-266,80,166}) then dragging="volume"; volume_at(); draw(); return end
    if inside({28,h-74,w-56,20}) then dragging="seek"; seek_at(); draw(); return end
    for _,b in ipairs(buttons) do if inside(b.r) then b.cb(); draw(); return end end
    mp.commandv("cycle","pause")
end
local function wheel(step)
    if expanded or inside({w-240,h-44,80,34}) then volume(property("volume",60)+step*5); shown_at=mp.get_time(); draw() end
end
mp.add_forced_key_binding("MOUSE_MOVE","den-motion",function() local mx,my=mp.get_mouse_pos(); pointer(mx,my) end)
mp.add_forced_key_binding("MOUSE_LEAVE","den-leave",function() x,y=-1,-1; expanded=false; draw() end)
mp.add_forced_key_binding("MBTN_LEFT","den-click",click,{complex=true})
mp.add_forced_key_binding("WHEEL_UP","den-volume-up",function() wheel(1) end,{repeatable=true})
mp.add_forced_key_binding("WHEEL_DOWN","den-volume-down",function() wheel(-1) end,{repeatable=true})
mp.add_forced_key_binding("ESC","den-back",function() mp.commandv("quit") end)
-- Deterministic input for the null-video and nested tests. They use their own mpv IPC.
mp.register_script_message("den-pointer",function(nx,ny) pointer(tonumber(nx),tonumber(ny)) end)
mp.register_script_message("den-click",function(event) click({event=event or "press"}) end)
mp.register_script_message("den-wheel",function(step) wheel(tonumber(step)) end)
local function read_palette()
    local file=io.open(opt.palette,"r")
    if file then local data=utils.parse_json(file:read("*a")); file:close(); if data then colors=data end end
    draw()
end
for _,name in ipairs({"volume","mute","pause","time-pos","duration","track-list","osd-dimensions"}) do
    mp.observe_property(name,"native",function() draw() end)
end
mp.add_periodic_timer(.3,read_palette)
shown_at=mp.get_time(); read_palette()
mp.msg.info("Den TV controller loaded for "..opt.screen)
