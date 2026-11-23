// A small Markdown renderer for the review text: headings, paragraphs, lists,
// tables, emphasis, code and links. Everything is escaped first, so text from
// the model or from paper records can never become HTML.
"use strict";

window.Markdown = (() => {
  const escape = (text) => text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

  function inline(text) {
    let html = escape(text);
    const codes = [];
    html = html.replace(/`([^`]+)`/g, (match, code) => { codes.push(code); return `\u0000${codes.length - 1}\u0000`; });
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/(^|[^*\w])\*([^*\s][^*]*?)\*(?!\w)/g, "$1<em>$2</em>");
    html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    html = html.replace(/(^|[\s(])(https?:\/\/[^\s<)]+[^\s<).,;])/g, '$1<a href="$2" target="_blank" rel="noopener noreferrer">$2</a>');
    html = html.replace(/\[(P\d+\?(?:,\s*P\d+\?)*)\]/g, '<span class="missing-cite">[$1]</span>');
    return html.replace(/\u0000(\d+)\u0000/g, (match, index) => `<code>${codes[Number(index)]}</code>`);
  }

  function cells(line) {
    return line.trim().replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim());
  }

  function render(source) {
    const lines = (source || "").replace(/\r\n?/g, "\n").split("\n");
    const out = [];
    let index = 0;
    while (index < lines.length) {
      const line = lines[index];
      if (!line.trim()) { index += 1; continue; }
      const heading = /^(#{1,4})\s+(.*)$/.exec(line);
      if (heading) {
        const level = heading[1].length;
        out.push(`<h${level}>${inline(heading[2])}</h${level}>`);
        index += 1;
        continue;
      }
      if (/^\s*\|.*\|\s*$/.test(line) && index + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[index + 1])) {
        const head = cells(line);
        index += 2;
        const rows = [];
        while (index < lines.length && /^\s*\|.*\|\s*$/.test(lines[index])) { rows.push(cells(lines[index])); index += 1; }
        out.push("<table><thead><tr>" + head.map((cell) => `<th>${inline(cell)}</th>`).join("") + "</tr></thead><tbody>"
          + rows.map((row) => "<tr>" + row.map((cell) => `<td>${inline(cell)}</td>`).join("") + "</tr>").join("") + "</tbody></table>");
        continue;
      }
      const listItem = /^\s*([-*+]|\d+[.)])\s+/;
      if (listItem.test(line)) {
        const ordered = /^\s*\d/.test(line);
        const items = [];
        while (index < lines.length && listItem.test(lines[index])) {
          let item = lines[index].replace(listItem, "");
          index += 1;
          while (index < lines.length && /^\s{2,}\S/.test(lines[index]) && !listItem.test(lines[index])) { item += " " + lines[index].trim(); index += 1; }
          items.push(`<li>${inline(item)}</li>`);
        }
        out.push(ordered ? `<ol>${items.join("")}</ol>` : `<ul>${items.join("")}</ul>`);
        continue;
      }
      if (/^>\s?/.test(line)) {
        const quote = [];
        while (index < lines.length && /^>\s?/.test(lines[index])) { quote.push(lines[index].replace(/^>\s?/, "")); index += 1; }
        out.push(`<blockquote>${inline(quote.join(" "))}</blockquote>`);
        continue;
      }
      const paragraph = [];
      while (index < lines.length && lines[index].trim() && !/^(#{1,4}\s|\s*([-*+]|\d+[.)])\s|>)/.test(lines[index]) && !/^\s*\|.*\|\s*$/.test(lines[index])) {
        paragraph.push(lines[index].trim());
        index += 1;
      }
      if (!paragraph.length) { paragraph.push(lines[index].trim()); index += 1; }
      out.push(`<p>${inline(paragraph.join(" "))}</p>`);
    }
    return out.join("\n");
  }

  return { render, escape };
})();
