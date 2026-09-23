export type UiDumpPayload = {
  xml: string;
  source?: string;
  complete?: boolean;
  warning?: string;
};

export type UiTreeNode = {
  tag: string;
  attributes: Record<string, string>;
  text: string;
  children: UiTreeNode[];
};

export type ParsedUiDump = {
  root?: UiTreeNode;
  nodeCount: number;
  truncated: boolean;
  recovered: boolean;
  error?: string;
};

const truncatedSuffix = /\.\.\. <truncated \d+ chars>\s*$/;

export function isUiDumpPayload(value: unknown): value is UiDumpPayload {
  return typeof value === "object"
    && value !== null
    && typeof (value as Record<string, unknown>).xml === "string";
}

function elementToTree(element: Element): UiTreeNode {
  const attributes = Object.fromEntries(
    Array.from(element.attributes, (attribute) => [attribute.name, attribute.value]),
  );
  const text = Array.from(element.childNodes)
    .filter((child) => child.nodeType === Node.TEXT_NODE || child.nodeType === Node.CDATA_SECTION_NODE)
    .map((child) => child.textContent ?? "")
    .join(" ")
    .trim();
  return {
    tag: element.tagName,
    attributes,
    text,
    children: Array.from(element.children, elementToTree),
  };
}

function hasParserError(document: Document) {
  return document.documentElement?.localName.toLowerCase() === "parsererror"
    || document.getElementsByTagName("parsererror").length > 0;
}

function closeOpenXmlElements(xml: string) {
  const content = xml.replace(truncatedSuffix, "");
  const end = content.lastIndexOf(">");
  if (end < 0) return "";

  const completeTags = content.slice(0, end + 1);
  const openElements: string[] = [];
  const tagPattern = /<\/?([A-Za-z_][\w:.-]*)(?:\s[^<>]*?)?\/?>/g;
  for (const match of completeTags.matchAll(tagPattern)) {
    const tag = match[0];
    const name = match[1];
    if (tag.startsWith("</")) {
      const index = openElements.lastIndexOf(name);
      if (index >= 0) openElements.splice(index);
    } else if (!/\/\s*>$/.test(tag)) {
      openElements.push(name);
    }
  }

  return completeTags + openElements.reverse().map((name) => `</${name}>`).join("");
}

function countNodes(root: UiTreeNode): number {
  return 1 + root.children.reduce((count, child) => count + countNodes(child), 0);
}

export function parseUiDumpXml(xml: string, source?: string): ParsedUiDump {
  const truncated = truncatedSuffix.test(xml);
  if (!xml.trim()) {
    return { nodeCount: 0, truncated, recovered: false, error: "UI dump 为空" };
  }
  const parser = new DOMParser();

  if (source === "WEBVIEW_DEVTOOLS") {
    const document = parser.parseFromString(xml, "text/html");
    const root = document.documentElement;
    if (root) {
      const tree = elementToTree(root);
      return { root: tree, nodeCount: countNodes(tree), truncated, recovered: false };
    }
  } else {
    const document = parser.parseFromString(xml, "application/xml");
    if (!hasParserError(document) && document.documentElement) {
      const tree = elementToTree(document.documentElement);
      return { root: tree, nodeCount: countNodes(tree), truncated, recovered: false };
    }

    const repaired = closeOpenXmlElements(xml);
    if (repaired) {
      const partialDocument = parser.parseFromString(repaired, "application/xml");
      if (!hasParserError(partialDocument) && partialDocument.documentElement) {
        const tree = elementToTree(partialDocument.documentElement);
        return { root: tree, nodeCount: countNodes(tree), truncated, recovered: true };
      }
    }
  }

  return {
    nodeCount: 0,
    truncated,
    recovered: false,
    error: "无法解析 UI 层级数据",
  };
}
