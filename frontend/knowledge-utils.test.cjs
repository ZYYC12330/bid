const assert = require("node:assert/strict");
const {
  buildDefaultKnowledgeItems,
  buildKnowledgeItemsFromFields,
  canonicalFieldName,
  defaultImageContentForField,
  defaultContentForField,
  fieldNamesMatch,
  fileNameFromImageContent,
  getKnowledgeTypeOptions,
  isImageContent,
  propagateManualValue,
} = require("./knowledge-utils.js");

const defaultKnowledgeItems = buildDefaultKnowledgeItems(1, {
  projectName: "401.88项目箱室设备采购",
});

assert.ok(defaultKnowledgeItems.length >= 10);
assert.ok(defaultKnowledgeItems.some((item) => item.name === "投标人" && item.content === "航天晨光股份有限公司"));
assert.ok(defaultKnowledgeItems.some((item) => item.name === "法定代表人（单位负责人）身份证复印件正面" && item.content === "./assets/legal-representative-id-front.jpg"));
assert.ok(defaultKnowledgeItems.some((item) => item.name === "法定代表人（单位负责人）身份证复印件反面" && item.content === "./assets/legal-representative-id-back.jpg"));
assert.equal(defaultKnowledgeItems[0].id, "kb_default_1");

const fields = [
  { id: "cover_project", section: "封面", fieldName: "项目名称", fieldType: "TEXT", manualValue: "" },
  { id: "letter_project", section: "投标函", fieldName: "项目名称", fieldType: "TEXT", manualValue: "" },
  { id: "bidder", section: "封面", fieldName: "投标人", fieldType: "TEXT", manualValue: "" },
  { id: "bidder_name", section: "投标函", fieldName: "投标人名称", fieldType: "TEXT", manualValue: "" },
  { id: "filing_no", section: "资格", fieldName: "备案号", fieldType: "TEXT", manualValue: "" },
  { id: "filing_number", section: "资格", fieldName: "备案号码", fieldType: "TEXT", manualValue: "" },
  { id: "established_at", section: "资格", fieldName: "成立时间", fieldType: "TEXT", manualValue: "" },
  { id: "staff_count", section: "资格", fieldName: "员工总数", fieldType: "TEXT", manualValue: "" },
  { id: "filled_date", section: "封面", fieldName: "日期", fieldType: "TEXT", manualValue: "" },
  { id: "postal_code", section: "资格", fieldName: "邮政编码", fieldType: "TEXT", manualValue: "" },
  { id: "seal", section: "封面", fieldName: "公章", fieldType: "Image", manualValue: "" },
];

const knowledgeItems = buildKnowledgeItemsFromFields(fields, 1, {
  projectName: "智慧园区综合管理平台建设项目",
});

assert.deepEqual(
  knowledgeItems.map((item) => [item.name, item.type, item.content, item.fileName]),
  [
    ["投标人", "TEXT", "航天晨光股份有限公司", ""],
    ["备案号", "TEXT", "HTCG-BA-2026-0428", ""],
    ["成立时间", "TEXT", "1999年9月30日", ""],
    ["员工总数", "TEXT", "1286人", ""],
    ["日期", "TEXT", "2026年4月28日", ""],
    ["邮政编码", "TEXT", "211100", ""],
    ["公章", "Image", "./assets/legal-representative-id-front.jpg", "legal-representative-id-front.jpg"],
  ],
);

assert.equal(
  defaultContentForField(
    { fieldName: "项目名称", fieldType: "TEXT" },
    { projectName: "智慧园区综合管理平台建设项目" },
  ),
  "智慧园区综合管理平台建设项目",
);
assert.equal(defaultContentForField({ fieldName: "项目名称", fieldType: "TEXT" }), "项目名称待确认");

assert.deepEqual(getKnowledgeTypeOptions(fields), ["TEXT", "Image"]);

assert.equal(canonicalFieldName("投标人名称"), "投标人");
assert.equal(canonicalFieldName("备案号码"), "备案");
assert.equal(canonicalFieldName("备案编号"), "备案");
assert.equal(fieldNamesMatch("投标人", "投标人名称"), true);
assert.equal(fieldNamesMatch("备案号", "备案号码"), true);
assert.equal(fieldNamesMatch("备案号", "备案编号"), true);
assert.equal(fieldNamesMatch("投标人", "投标人名称和地址"), false);

assert.equal(isImageContent("data:image/png;base64,abc123"), true);
assert.equal(isImageContent("./assets/legal-representative-id-front.jpg"), true);
assert.equal(isImageContent("已上传：投标人公章图片"), false);
assert.equal(fileNameFromImageContent("./assets/legal-representative-id-front.jpg"), "legal-representative-id-front.jpg");
assert.equal(fileNameFromImageContent("/knowledge-images/seal.png?version=1"), "seal.png");
assert.equal(fileNameFromImageContent("data:image/png;base64,abc123"), "");
assert.equal(defaultImageContentForField("法定代表人（单位负责人）身份证复印件正面"), "./assets/legal-representative-id-front.jpg");
assert.equal(defaultImageContentForField("法定代表人（单位负责人）身份证复印件反面"), "./assets/legal-representative-id-back.jpg");

const synced = propagateManualValue(fields, "cover_project", "401.88项目箱室设备采购");
assert.deepEqual(
  synced.map((item) => [item.id, item.manualValue]),
  [
    ["cover_project", "401.88项目箱室设备采购"],
    ["letter_project", "401.88项目箱室设备采购"],
    ["bidder", ""],
    ["bidder_name", ""],
    ["filing_no", ""],
    ["filing_number", ""],
    ["established_at", ""],
    ["staff_count", ""],
    ["filled_date", ""],
    ["postal_code", ""],
    ["seal", ""],
  ],
);

const fuzzySynced = propagateManualValue(fields, "bidder", "航天晨光股份有限公司");
assert.deepEqual(
  fuzzySynced.map((item) => [item.id, item.manualValue]),
  [
    ["cover_project", "401.88项目箱室设备采购"],
    ["letter_project", "401.88项目箱室设备采购"],
    ["bidder", "航天晨光股份有限公司"],
    ["bidder_name", "航天晨光股份有限公司"],
    ["filing_no", ""],
    ["filing_number", ""],
    ["established_at", ""],
    ["staff_count", ""],
    ["filled_date", ""],
    ["postal_code", ""],
    ["seal", ""],
  ],
);
