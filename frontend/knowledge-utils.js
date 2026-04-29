(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.KnowledgeUtils = factory();
  }
})(typeof window !== "undefined" ? window : globalThis, function () {
  const DEFAULT_CONTENT_BY_NAME = {
    投标人: "航天晨光股份有限公司",
    投标人名称: "航天晨光股份有限公司",
    招标编号: "GKZH-25ZXH856",
    公司名称: "航天晨光股份有限公司",
    公司简称: "航天晨光",
    股票代码: "600501",
    英文名称: "Aerosun Corporation",
    法定代表人: "赵康",
    姓名: "赵康",
    性别: "男",
    职务: "董事长",
    董事长: "赵康",
    注册地址: "江苏省南京市江宁区天元中路188号",
    办公地址: "江苏省南京市江宁区天元中路188号",
    公司地址: "江苏省南京市江宁区天元中路188号",
    统一社会信用代码: "91320000714091899R",
    注册资本: "42782.42万元人民币",
    股本: "427,824,200股",
    成立日期: "1999年9月30日",
    成立时间: "1999年9月30日",
    设立日期: "1999年9月30日",
    设立时间: "1999年9月30日",
    员工总数: "1286人",
    员工数量: "1286人",
    职工总数: "1286人",
    在册员工: "1286人",
    日期: "2026年4月28日",
    投标日期: "2026年4月28日",
    填报日期: "2026年4月28日",
    备案号: "HTCG-BA-2026-0428",
    公司网址: "www.aerosun.cn",
    网址: "www.aerosun.cn",
    联系电话: "025-52826031",
    邮编: "211100",
    邮政编码: "211100",
    委托代理人: "王五",
    企业简介:
      "航天晨光股份有限公司，股票简称航天晨光，股票代码600501，英文名称Aerosun Corporation；法定代表人赵康，注册地址和办公地址为江苏省南京市江宁经济技术开发区将军大道199号。",
    公司简介:
      "航天晨光股份有限公司，股票简称航天晨光，股票代码600501，英文名称Aerosun Corporation；法定代表人赵康，注册地址和办公地址为江苏省南京市江宁经济技术开发区将军大道199号。",
    开户行: "中国工商银行股份有限公司南京雨花支行",
    基本账户开户银行: "中国工商银行股份有限公司南京雨花支行",
    基本账户银行账号: "4301013709002090856",
    增值税普通发票信息: "91320000714091899R",
    传真: "025-52826501",
    传真号码: "025-52826501",
    传真电话: "025-52826501",
    传真联系方式: "025-52826501",
    传真联系方式: "025-52826501",
  };

  const DEFAULT_IMAGE_CONTENT = {
    front: "./assets/legal-representative-id-front.jpg",
    back: "./assets/legal-representative-id-back.jpg",
  };

  const DEFAULT_KNOWLEDGE_FIELDS = [
    { name: "投标人", type: "TEXT" },
    { name: "法定代表人", type: "TEXT" },
    { name: "职务", type: "TEXT" },
    { name: "统一社会信用代码", type: "TEXT" },
    { name: "注册地址", type: "TEXT" },
    { name: "办公地址", type: "TEXT" },
    { name: "联系电话", type: "TEXT" },
    { name: "邮政编码", type: "TEXT" },
    { name: "开户行", type: "TEXT" },
    { name: "基本账户银行账号", type: "TEXT" },
    { name: "企业简介", type: "TEXT" },
    { name: "法定代表人（单位负责人）身份证复印件正面", type: "Image" },
    { name: "法定代表人（单位负责人）身份证复印件反面", type: "Image" },
  ];

  function normalizeFieldName(name) {
    return String(name || "")
      .replace(/[：:\s]/g, "")
      .trim();
  }

  const FIELD_SUFFIXES = ["名称", "号码", "编号", "编码", "代码"];

  function canonicalFieldName(name) {
    let normalized = normalizeFieldName(name);
    let changed = true;
    while (changed) {
      changed = false;
      for (const suffix of FIELD_SUFFIXES) {
        if (normalized.length > suffix.length + 1 && normalized.endsWith(suffix)) {
          normalized = normalized.slice(0, -suffix.length);
          changed = true;
          break;
        }
      }
    }
    if (normalized.length <= 4 && normalized.endsWith("号")) {
      normalized = normalized.slice(0, -1);
    }
    return normalized;
  }

  function fieldNamesMatch(leftName, rightName) {
    const left = normalizeFieldName(leftName);
    const right = normalizeFieldName(rightName);
    if (!left || !right) return false;
    if (left === right) return true;

    const leftCanonical = canonicalFieldName(left);
    const rightCanonical = canonicalFieldName(right);
    return Boolean(leftCanonical && rightCanonical && leftCanonical === rightCanonical);
  }

  function formatFieldType(type) {
    const raw = String(type || "TEXT").trim();
    if (/^image$/i.test(raw)) return "Image";
    if (/^text$/i.test(raw)) return "TEXT";
    return raw || "TEXT";
  }

  function isImageContent(content) {
    const value = String(content || "");
    return /^data:image\//i.test(value) || /\.(png|jpe?g|webp|gif|svg)(\?.*)?$/i.test(value);
  }

  function defaultImageContentForField(name) {
    const normalizedName = normalizeFieldName(name);
    if (/反面|背面|背页|国徽|签发机关|有效期限/.test(normalizedName)) return DEFAULT_IMAGE_CONTENT.back;
    return DEFAULT_IMAGE_CONTENT.front;
  }

  function fileNameFromImageContent(content) {
    const value = String(content || "");
    const match = value.match(/([^/?#]+\.(?:png|jpe?g|webp|gif|svg))(?:[?#].*)?$/i);
    return match ? match[1] : "";
  }

  function isProjectNameField(name) {
    return fieldNamesMatch(name, "项目名称");
  }

  function defaultContentForField(item, context = {}) {
    const name = item.name || item.fieldName || item.field_name || "";
    const normalizedName = normalizeFieldName(name);
    if (isProjectNameField(name)) {
      return String(
        context.projectName ||
          context.project_name ||
          item.projectName ||
          item.project_name ||
          "",
      ).trim() || `${name || "资料"}待确认`;
    }
    if (DEFAULT_CONTENT_BY_NAME[normalizedName]) return DEFAULT_CONTENT_BY_NAME[normalizedName];
    const canonicalName = canonicalFieldName(name);
    if (DEFAULT_CONTENT_BY_NAME[canonicalName]) return DEFAULT_CONTENT_BY_NAME[canonicalName];
    if (formatFieldType(item.type || item.fieldType || item.field_type) === "Image") {
      return defaultImageContentForField(name);
    }
    if (/成立|设立/.test(normalizedName)) return "1999年9月30日";
    if (/员工|职工|人数|人员数量|人员总数/.test(normalizedName)) return "1286人";
    if (/日期|时间/.test(normalizedName)) return "2026年4月28日";
    if (/电话|联系方式/.test(normalizedName)) return "025-52826031";
    if (/地址|地点/.test(normalizedName)) return "江苏省南京市江宁经济技术开发区将军大道199号";
    if (/金额|报价|价格|费用/.test(normalizedName)) return "人民币壹佰万元整";
    if (/编号|号码|代码|证号|备案/.test(normalizedName)) return "HTCG-2026-0428";
    if (/名称|单位|机构|公司/.test(normalizedName)) return "航天晨光股份有限公司";
    return `${name || "资料"}待确认`;
  }

  function buildKnowledgeItemsFromFields(items, startIndex = 1, context = {}) {
    const seen = new Set();
    const result = [];
    items.forEach((item) => {
      const name = item.fieldName || item.field_name || item.name || "未命名字段";
      if (isProjectNameField(name)) return;
      const key = canonicalFieldName(name);
      if (!key || seen.has(key)) return;
      seen.add(key);
      const content = item.manualValue || item.manual_value || defaultContentForField(item, context);
      result.push({
        id: `kb_ai_${startIndex + result.length}`,
        name,
        type: formatFieldType(item.fieldType || item.field_type || item.type),
        content,
        fileName: item.fileName || item.file_name || fileNameFromImageContent(content),
        fieldKey: key,
      });
    });
    return result;
  }

  function buildDefaultKnowledgeItems(startIndex = 1, context = {}) {
    return DEFAULT_KNOWLEDGE_FIELDS.map((item, index) => {
      const content = defaultContentForField(
        { fieldName: item.name, fieldType: item.type },
        context,
      );
      return {
        id: `kb_default_${startIndex + index}`,
        name: item.name,
        type: formatFieldType(item.type),
        content,
        fileName: fileNameFromImageContent(content),
        fieldKey: canonicalFieldName(item.name),
      };
    });
  }

  function getKnowledgeTypeOptions(items) {
    const values = items.map((item) => formatFieldType(item.fieldType || item.field_type || item.type));
    return [...new Set(values.length ? values : ["TEXT"])];
  }

  function propagateManualValue(items, sourceItemId, value) {
    const source = items.find((item) => item.id === sourceItemId || item.item_id === sourceItemId);
    if (!source) return items;
    const sourceName = source.fieldName || source.field_name || source.name;
    return items.map((item) => {
      const itemName = item.fieldName || item.field_name || item.name;
      if (!fieldNamesMatch(itemName, sourceName)) return item;
      item.manualValue = value;
      if (item.raw) item.raw.manual_value = value;
      return item;
    });
  }

  return {
    buildDefaultKnowledgeItems,
    buildKnowledgeItemsFromFields,
    canonicalFieldName,
    defaultContentForField,
    defaultImageContentForField,
    fieldNamesMatch,
    fileNameFromImageContent,
    formatFieldType,
    getKnowledgeTypeOptions,
    isImageContent,
    isProjectNameField,
    normalizeFieldName,
    propagateManualValue,
  };
});
