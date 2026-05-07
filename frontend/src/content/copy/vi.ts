/**
 * Vietnamese-first UI copy for KG Explorer.
 * Glossary: keep Latin tokens for tech names (Neo4j, Cypher, model IDs) where clarity beats translation.
 */
export const glossary = {
  neo4jBrowser: 'Neo4j Browser',
  cypher: 'Cypher',
  reasoningMode: 'Suy luận từng bước',
} as const;

export const vi = {
  metaTitle: 'KG Explorer — Công ty niêm yết Việt Nam',

  brandName: 'KG Explorer',
  brandSub: 'Bảng điều khiển phân tích quan hệ giữa các công ty niêm yết tại Việt Nam',
  /** Attribution in header (mailto optional in UI) */
  designCredit: 'Designed by ptbinh@csc.hcmus.edu.vn',

  crawlCta: 'Cập nhật dữ liệu mới nhất',
  crawlRunning: 'Đang cập nhật…',
  themeToggle: 'Đổi giao diện',
  themeDark: 'Tối',
  themeLight: 'Sáng',

  /** Expandable hero inside top bar */
  heroToggleExpand: 'Mở rộng giới thiệu',
  heroToggleCollapse: 'Thu gọn giới thiệu',
  heroKicker: 'Trí tuệ quan hệ doanh nghiệp',
  heroTitle:
    'Theo dõi quyền kiểm soát, sở hữu và ảnh hưởng tiềm ẩn trên thị trường.',
  heroSummary:
    'Khám phá đồ thị trực quan, đọc luật suy luận pháp lý và mở trợ lý khi cần giải thích ngữ cảnh hoặc truy vấn Cypher — luôn giữ nguyên ngữ cảnh bạn đang xem.',

  heroStatEntities: 'Thực thể',
  heroStatLinks: 'Quan hệ',
  /** Inferred / hidden ties count — replaces vague “Suy luận” label */
  heroStatHidden: 'Quan hệ ẩn',

  railSnapshot: 'Ảnh chụp nhanh',
  railSnapshotHint:
    'Tổng quan số liệu trong KG: công ty, cá nhân và quan hệ đã đồng bộ — trước khi bạn mở đồ thị chi tiết.',
  railExplore: 'Khám phá',
  railExploreHint:
    'Chọn chế độ công ty hoặc cá nhân, rồi nhấn vào một nút trên đồ thị để xem thêm liên kết.',
  railInference: 'Suy luận',
  railInferenceHint:
    'Xem các luật suy luận pháp lý và gợi ý điều tra nhanh từ dữ liệu.',

  overviewTitle: 'Tổng quan KG',
  overviewSync: 'Đồng bộ',
  listedCompanies: 'Công ty niêm yết',
  persons: 'Cá nhân',
  edgesInDb: 'Quan hệ trong CSDL',
  /** Was “Quan hệ suy luận” — clarified */
  inferredEdgesLabel: 'Quan hệ được suy luận',
  lastUpdated: 'Cập nhật gần nhất',

  marketFootprint: 'Phân bố theo sàn',
  companiesUnit: 'công ty',
  loading: 'Đang tải…',
  loadFailed: 'Không thể tải',

  exploreMode: 'Chế độ khám phá',
  modeCompanies: 'Công ty',
  modePersons: 'Cá nhân',

  quickEntry: 'Xem nhanh các công ty',
  criteriaDegree: 'Nhiều liên kết nhất',
  criteriaShareholders: 'Nhiều cổ đông nhất',
  criteriaSubsidiaries: 'Nhiều công ty con nhất',
  criteriaLeadership: 'Nhiều chức danh lãnh đạo (ghi nhận)',
  criteriaMarketCap: 'Công ty có vốn hoá cao nhất (proxy)',

  inferenceRulesTitle: 'Quan hệ ẩn',
  ruleLogicLabel: 'Logic',
  ruleInferredLabel: 'Suy ra',
  suggestedInvestigation: 'Gợi ý điều tra',

  graphLoaderCompanies: 'Đang tải công ty…',
  graphLoaderPersons: 'Đang tải lãnh đạo (công ty niêm yết)…',
  graphLoaderDraw: 'Đang vẽ đồ thị…',
  graphHint:
    'Chọn một công ty trên đồ thị để xem các mối quan hệ',

  commandMode: 'Chế độ',
  commandAlert: 'Gợi ý',
  modeLabelCompanies: 'Đồ thị công ty',
  modeLabelPersons: 'Đồ thị lãnh đạo',
  modeLabelQuery: 'Đồ thị từ truy vấn',
  alertCompanies: 'Theo dõi các cụm có quan hệ được suy luận',
  alertPersons: 'Mở rộng từng người để xem thêm liên quan',
  alertQuery: 'Đồ thị con do trợ lý tạo từ truy vấn',

  primaryExploreCompanies: 'Bắt đầu với công ty',
  primaryOpenAssistant: 'Mở trợ lý',
  graphExploreCompanies: 'Khám phá công ty',
  /** Was “Xem mạng lãnh đạo” */
  graphLeadershipNetwork: 'Mạng lãnh đạo ↔ công ty',
  graphAskAssistant: 'Hỏi trợ lý',

  legendCompany: 'Công ty',
  legendPerson: 'Cá nhân',
  legendInstitution: 'Tổ chức',
  legendHiddenEdge: 'Quan hệ ẩn',

  assistantKicker: 'Phân tích hỗ trợ',
  assistantHeadline:
    'Đồ thị rối? Mở trợ lý để được giải thích ngắn gọn hoặc gợi ý truy vấn Cypher.',
  assistantTitle: 'Trợ lý phân tích',
  sessionPlaceholder: '— Phiên hiện tại —',
  saveSession: 'Lưu phiên',
  clearSessions: 'Xóa tất cả',
  searchPlaceholder: 'Tìm công ty, cá nhân… (Ctrl+K)',
  chatPlaceholder: 'Hỏi về công ty, cổ đông hoặc quan hệ…',
  send: 'Gửi',
  reasoningToggle: glossary.reasoningMode,

  chatWelcome:
    'Xin chào! Hãy nhập câu hỏi về công ty, cổ đông hoặc quan hệ sở hữu.',

  cypherBlock: 'Truy vấn Cypher',
  /** Sections inside the query overlay */
  queryCodeHeading: 'Mã Cypher',
  queryLogHeading: 'Nhật ký xử lý',
  qresultCollapse: 'Thu gọn',
  qresultExpand: 'Mở rộng',

  nodeDetailExpand: 'Mở rộng mối quan hệ',
  nodeDetailCollapse: 'Thu gọn quan hệ',
  nodeDetailClose: 'Đóng',
  nodeDetailMaximize: 'Phóng to / Thu nhỏ',
  nodeDetailWiden: 'Mở rộng khung',
  nodeDetailNarrow: 'Thu khung',
  badgeCompany: 'Công ty',
  badgePerson: 'Cá nhân',
  badgeInstitution: 'Tổ chức',

  sidebarToggle: 'Thu/Mở bảng trái',
  sidebarWiden: 'Đổi kích thước bảng trái',
  rightToggle: 'Thu/Mở trợ lý',
  rightWiden: 'Đổi kích thước bảng phải',

  llmSettingsOpen: 'Cấu hình LLM',
  llmSettingsTitle: 'Kết nối LLM',
  llmBackend: 'Backend',
  llmBaseUrl: 'Base URL',
  llmModel: 'Model',
  llmApiKey: 'API key',
  llmApiKeyHint: 'Để trống để giữ nguyên. OpenAI / OpenRouter / vLLM có bảo vệ Bearer.',
  llmClearApiKey: 'Xóa API key đã lưu',
  llmSave: 'Lưu',
  llmCancel: 'Đóng',
  llmSettingsSaved: 'Đã lưu cấu hình.',

  loadingOverlay: 'Đang xử lý…',
  toastEmptyQuery: 'Vui lòng nhập câu hỏi',
  toastAnswered: 'Đã trả lời',
  toastErrorPrefix: 'Lỗi',

  leftCollapsedAria: 'Bảng điều hướng trái đang thu gọn',
  rightCollapsedAria: 'Bảng trợ lý đang thu gọn',
} as const;

export const suggestedPrompts: string[] = [
  'Có cá nhân nào vừa là Chủ tịch HĐQT của một công ty vừa là cổ đông của công ty khác không?',
  'Những người thân của Chủ tịch tập đoàn Vingroup (VIC) có làm cổ đông của doanh nghiệp khác không?',
  'Có công ty con nào của ngân hàng MBB lại tiếp tục có công ty con của riêng nó tạo thành chuỗi 2 cấp bậc không?',
  'Cho biết những công ty nào là công ty con của VNM nhưng lại bị sở hữu bởi một cổ đông Tổ chức khác?',
  'Ai là cá nhân vừa nắm giữ chức vụ tại FPT, vừa là cổ đông của một công ty ngân hàng?',
  'Hồ Hùng Anh và những người thân trong gia đình ông đang sở hữu tổng cộng những công ty nào?',
  'Mô tả tất cả các sợi dây liên kết gián tiếp giữa Vingroup (VIC) và Vinhomes (VHM) qua các công ty con và cổ đông.',
  'Tìm các công ty con do Masan (MSN) sở hữu nhưng MSN không nắm 100% cổ phần mà bị pha loãng bởi cá nhân khác?',
];
