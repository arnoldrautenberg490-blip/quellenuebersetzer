--[[
Pandoc-Filter des Quellenübersetzers.

1. HTML-Tabellen im Markdown werden in echte Pandoc-Tabellen umgewandelt
   (verbundene Zellen bleiben erhalten, auch in DOCX und PDF).
2. Seitenangaben (<!-- Seite n -->) werden als dezente Marke [S. n] sichtbar.
3. Markierungen werden je Ausgabeformat eingefärbt und mit einer Fußnote versehen:
     .a   Lesung unsicher     (orange, gepunktet unterstrichen)
     .b1  Bedeutungswandel    (blau, unterstrichen)
     .b2  Begriff der Zeit    (grün, gestrichelt unterstrichen)
4. Hinweis- und Warnkästen (::: hinweis / ::: warnung).
]]

local COLORS = { a = "#b35c00", b1 = "#3b5ba9", b2 = "#2f7d6d" }
local DOCX_STYLES = { a = "Lesung unsicher", b1 = "Bedeutungswandel", b2 = "Begriff der Zeit" }
local TYPST_DECO = {
  a = 'underline(stroke: (paint: rgb("#b35c00"), thickness: 0.8pt, dash: "dotted"), offset: 2pt)',
  b1 = 'underline(stroke: (paint: rgb("#3b5ba9"), thickness: 0.6pt), offset: 2pt)',
  b2 = 'underline(stroke: (paint: rgb("#2f7d6d"), thickness: 0.6pt, dash: "dashed"), offset: 2pt)',
}

local function attr(el, key)
  local v = el.attributes[key]
  if v == nil or v == "" then v = el.attributes["data-" .. key] end
  if v == "" then return nil end
  return v
end

local function category(el)
  for _, c in ipairs(el.classes) do
    if c == "a" or c == "b1" or c == "b2" then return c end
  end
  return nil
end

local function split(s, sep)
  local out = {}
  if not s then return out end
  for part in string.gmatch(s, "([^" .. sep .. "]+)") do table.insert(out, part) end
  return out
end

local function quote(s) return "„" .. s .. "“" end

local function note_text(cat, el)
  local hinweis = attr(el, "hinweis")
  if hinweis then return hinweis end
  if cat == "a" then
    if attr(el, "unleserlich") then return "Unleserliche Stelle." end
    local orig = split(attr(el, "lesarten"), "|")
    local de = split(attr(el, "lesarten_de"), "|")
    local sicher = tonumber(attr(el, "sicher") or "")
    local parts = {}
    for i, o in ipairs(orig) do
      local d = de[i]
      if d and d ~= o then
        table.insert(parts, quote(o) .. " (" .. d .. ")")
      else
        table.insert(parts, quote(o))
      end
    end
    local txt = "Lesung unsicher"
    if sicher then txt = txt .. string.format(" (Sicherheit etwa %d %%)", math.floor(sicher * 100 + 0.5)) end
    if #parts > 1 then
      txt = txt .. ". Mögliche Lesarten: " .. table.concat(parts, " · ") .. "."
    elseif #parts == 1 then
      txt = txt .. ". Gelesen: " .. parts[1] .. "."
    else
      txt = txt .. "."
    end
    return txt
  end
  local orig = attr(el, "original")
  local head = (cat == "b1") and "Bedeutungswandel" or "Begriff der Zeit"
  local txt = head
  if orig then txt = txt .. ": " .. quote(orig) end
  if cat == "b1" then
    local damals, heute = attr(el, "damals"), attr(el, "heute")
    if damals then txt = txt .. " – damals: " .. damals end
    if heute then txt = txt .. "; heute: " .. heute end
  end
  local erkl = attr(el, "erkl")
  if erkl then txt = txt .. ". " .. erkl end
  local beleg = attr(el, "beleg")
  if beleg then txt = txt .. " (Beleg: " .. beleg .. ")" end
  if not txt:match("[%.%)]$") then txt = txt .. "." end
  return txt
end

local function styled(cat, content)
  if FORMAT:match("docx") then
    return pandoc.Span(content, pandoc.Attr("", {}, { ["custom-style"] = DOCX_STYLES[cat] }))
  elseif FORMAT:match("typst") then
    local out = { pandoc.RawInline("typst", "#text(fill: rgb(\"" .. COLORS[cat] .. "\"))[#" .. TYPST_DECO[cat] .. "[") }
    for _, c in ipairs(content) do table.insert(out, c) end
    table.insert(out, pandoc.RawInline("typst", "]]"))
    return out
  else
    return pandoc.Span(content, pandoc.Attr("", { "mark-" .. cat }, {}))
  end
end

local function Span(el)
  local cat = category(el)
  if not cat then return nil end
  local result = styled(cat, el.content)
  local note = pandoc.Note({ pandoc.Para({ pandoc.Str(note_text(cat, el)) }) })
  if type(result) == "table" and result.t == nil then
    table.insert(result, note)
    return result
  end
  return { result, note }
end

local function box(el, kind)
  if FORMAT:match("docx") then
    local out = {}
    for _, b in ipairs(el.content) do
      table.insert(out, pandoc.Div({ b }, pandoc.Attr("", {}, { ["custom-style"] = kind })))
    end
    return out
  elseif FORMAT:match("typst") then
    local fill, stroke = "#f6f1e7", "#b9ae98"
    if kind == "Warnung" then fill, stroke = "#fbe9e6", "#b3402f" end
    local out = { pandoc.RawBlock("typst", "#block(fill: rgb(\"" .. fill .. "\"), stroke: 0.8pt + rgb(\"" .. stroke .. "\"), inset: 10pt, radius: 3pt, width: 100%)[") }
    for _, b in ipairs(el.content) do table.insert(out, b) end
    table.insert(out, pandoc.RawBlock("typst", "]"))
    return out
  end
  return nil
end

local function Div(el)
  if el.classes:includes("warnung") then return box(el, "Warnung") end
  if el.classes:includes("hinweis") then return box(el, "Hinweis") end
  return nil
end

local function RawBlock(el)
  if el.format ~= "html" then return nil end
  local seite = el.text:match("^<!%-%-%s*Seite%s+(%S+)%s*%-%->$")
  if seite then
    local mark = pandoc.Span({ pandoc.Str("[S. " .. seite .. "]") }, pandoc.Attr("", { "seite" }, {}))
    if FORMAT:match("docx") then
      mark = pandoc.Span({ pandoc.Str("[S. " .. seite .. "]") }, pandoc.Attr("", {}, { ["custom-style"] = "Seitenangabe" }))
    elseif FORMAT:match("typst") then
      return pandoc.RawBlock("typst", "#text(size: 8pt, fill: rgb(\"#7a746a\"))[\\[S. " .. seite .. "\\]]")
    end
    return pandoc.Para({ mark })
  end
  if el.text:match("^%s*<[Tt][Aa][Bb][Ll][Ee]") then
    return pandoc.read(el.text, "html").blocks
  end
  return nil
end

-- Reihenfolge: zuerst Tabellen/Seitenangaben einlesen, dann Markierungen in allen (auch neuen) Elementen setzen.
local function Pandoc(doc)
  if FORMAT:match("typst") then
    table.insert(doc.blocks, 1, pandoc.RawBlock("typst",
      '#set table(stroke: 0.5pt + rgb("#b9ae98"), inset: 6pt)\n#show table.cell.where(y: 0): set text(weight: "bold")'))
  end
  return doc
end

return {
  { RawBlock = RawBlock },
  { Span = Span, Div = Div },
  { Pandoc = Pandoc },
}
