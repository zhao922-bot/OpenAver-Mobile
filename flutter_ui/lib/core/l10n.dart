class AppStrings {
  AppStrings(this.locale);

  final String locale;

  static const List<String> supportedLocales = [
    'zh-CN',
    'zh-TW',
    'ja',
    'en',
    'ko',
  ];

  bool get _isZhTw => locale == 'zh-TW';
  bool get _isJa => locale == 'ja';
  bool get _isEn => locale == 'en';
  bool get _isKo => locale == 'ko';

  String tr({
    required String zhCn,
    String? zhTw,
    String? ja,
    String? en,
    String? ko,
  }) {
    if (_isZhTw) return zhTw ?? zhCn;
    if (_isJa) return ja ?? en ?? zhCn;
    if (_isEn) return en ?? zhCn;
    if (_isKo) return ko ?? en ?? zhCn;
    return zhCn;
  }

  // Navigation tabs
  String get tabShowcase => tr(zhCn: '浏览', zhTw: '瀏覽', ja: 'ブラウズ', en: 'Showcase', ko: '라이브러리');
  String get tabSearch => tr(zhCn: '搜索', zhTw: '搜尋', ja: '検索', en: 'Search', ko: '검색');
  String get tabScanner => tr(zhCn: '片库', zhTw: '片庫', ja: '管理', en: 'Scanner', ko: '스캔');
  String get tabInsights => tr(zhCn: '分析', zhTw: '分析', ja: '分析', en: 'Insights', ko: '분석');
  String get tabSettings => tr(zhCn: '设置', zhTw: '設定', ja: '設定', en: 'Settings', ko: '설정');

  // Common actions
  String get confirm => tr(zhCn: '确认', zhTw: '確認', ja: '確認', en: 'Confirm', ko: '확인');
  String get cancel => tr(zhCn: '取消', zhTw: '取消', ja: 'キャンセル', en: 'Cancel', ko: '취소');
  String get save => tr(zhCn: '保存', zhTw: '儲存', ja: '保存', en: 'Save', ko: '저장');
  String get edit => tr(zhCn: '编辑', zhTw: '編輯', ja: '編集', en: 'Edit', ko: '편집');
  String get refresh => tr(zhCn: '刷新', zhTw: '重新整理', ja: '更新', en: 'Refresh', ko: '새로고침');
  String get delete => tr(zhCn: '删除', zhTw: '刪除', ja: '削除', en: 'Delete', ko: '삭제');
  String get close => tr(zhCn: '关闭', zhTw: '關閉', ja: '閉じる', en: 'Close', ko: '닫기');
  String get retry => tr(zhCn: '重试', zhTw: '重試', ja: '再試行', en: 'Retry', ko: '재시도');
  String get loading => tr(zhCn: '加载中…', zhTw: '載入中…', ja: '読み込み中…', en: 'Loading…', ko: '불러오는 중…');
  String get exitHint => tr(
        zhCn: '再按一次返回退出应用',
        zhTw: '再按一次返回退出應用程式',
        ja: 'もう一度戻ると終了します',
        en: 'Press back again to exit',
        ko: '뒤로 가기를 한 번 더 누르면 종료됩니다',
      );

  // Showcase
  String get searchLibraryHint => tr(
        zhCn: '搜索番号、标题、演员、片商、标签…',
        zhTw: '搜尋番號、標題、演員、片商、標籤…',
        ja: '品番・タイトル・女優・メーカー・タグを検索…',
        en: 'Search number, title, actress, maker, tag…',
        ko: '품번, 제목, 배우, 제작사, 태그 검색…',
      );
  String get allVideos => tr(zhCn: '全部', zhTw: '全部', ja: 'すべて', en: 'All', ko: '전체');
  String get favoritesOnly => tr(zhCn: '精选', zhTw: '精選', ja: 'お気に入り', en: 'Favorites', ko: '즐겨찾기');
  String get actresses => tr(zhCn: '女优', zhTw: '女優', ja: '女優', en: 'Actresses', ko: '배우');
  String get plot => tr(zhCn: '简介', zhTw: '簡介', ja: 'あらすじ', en: 'Synopsis', ko: '줄거리');
  String get refetchPlot => tr(zhCn: '重新获取', zhTw: '重新取得', ja: '再取得', en: 'Refetch', ko: '다시 가져오기');
  String get translateAi => tr(zhCn: 'AI 翻译', zhTw: 'AI 翻譯', ja: 'AI 翻訳', en: 'AI Translate', ko: 'AI 번역');
  String get showOriginal => tr(zhCn: '显示原文', zhTw: '顯示原文', ja: '原文を表示', en: 'Original', ko: '원문 보기');
  String get showTranslated => tr(zhCn: '显示译文', zhTw: '顯示譯文', ja: '訳文を表示', en: 'Translated', ko: '번역 보기');
  String get sampleImages => tr(zhCn: '剧照', zhTw: '劇照', ja: 'サンプル画像', en: 'Samples', ko: '샘플 이미지');
  String get similarVideos => tr(zhCn: '相似推荐', zhTw: '相似推薦', ja: '類似作品', en: 'Similar', ko: '비슷한 작품');
  String get playVideo => tr(zhCn: '播放影片', zhTw: '播放影片', ja: '再生', en: 'Play', ko: '재생');
  String get builtinPlayer => tr(zhCn: '内置播放器', zhTw: '內建播放器', ja: '内蔵プレーヤー', en: 'Built-in Player', ko: '내장 플레이어');
  String get externalPlayer => tr(zhCn: '外部播放器', zhTw: '外部播放器', ja: '外部プレーヤー', en: 'External Player', ko: '외부 플레이어');
  String get rescrape => tr(zhCn: '重刮元数据', zhTw: '重刮中繼資料', ja: '再スクレイプ', en: 'Rescrape', ko: '재스크랩');
  String get addTag => tr(zhCn: '添加标签', zhTw: '新增標籤', ja: 'タグ追加', en: 'Add tag', ko: '태그 추가');
  String get removeFromDb => tr(zhCn: '移出片库索引', zhTw: '移出片庫索引', ja: 'ライブラリから削除', en: 'Remove from library', ko: '라이브러리에서 제거');

  // Scanner
  String get scanLibrary => tr(zhCn: '扫描片库', zhTw: '掃描片庫', ja: 'スキャン開始', en: 'Scan Library', ko: '라이브러리 스캔');
  String get stopTask => tr(zhCn: '停止任务', zhTw: '停止任務', ja: 'タスク停止', en: 'Stop Task', ko: '작업 중지');
  String get checkMissing => tr(zhCn: '检查缺失项', zhTw: '檢查缺失項目', ja: '不足チェック', en: 'Check Missing', ko: '누락 항목 확인');
  String get backfillPlots => tr(zhCn: '补全简介', zhTw: '補全簡介', ja: 'あらすじ補完', en: 'Backfill Plots', ko: '줄거리 채우기');
  String get backfillSamples => tr(zhCn: '补全剧照', zhTw: '補全劇照', ja: 'サンプル補完', en: 'Backfill Samples', ko: '샘플 채우기');
  String get backfillTitles => tr(zhCn: '翻译标题', zhTw: '翻譯標題', ja: 'タイトル翻訳', en: 'Translate Titles', ko: '제목 번역');
  String get backfillNfo => tr(zhCn: '补全 NFO', zhTw: '補全 NFO', ja: 'NFO 補完', en: 'Backfill NFO', ko: 'NFO 채우기');
  String get backfillJellyfin => tr(zhCn: '补齐 Jellyfin 封面', zhTw: '補齊 Jellyfin 封面', ja: 'Jellyfin 画像補完', en: 'Jellyfin Art', ko: 'Jellyfin 이미지');
  String get renameNormalize => tr(zhCn: '文件命名整理', zhTw: '檔案命名整理', ja: 'リネーム整理', en: 'Normalize Names', ko: '파일명 정리');
  String get clearCache => tr(zhCn: '清空片库索引', zhTw: '清空片庫索引', ja: 'キャッシュ削除', en: 'Clear Index', ko: '인덱스 초기화');
}
