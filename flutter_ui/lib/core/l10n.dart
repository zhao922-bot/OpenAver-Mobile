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

  // Common actions & states
  String get confirm => tr(zhCn: '确认', zhTw: '確認', ja: '確認', en: 'Confirm', ko: '확인');
  String get cancel => tr(zhCn: '取消', zhTw: '取消', ja: 'キャンセル', en: 'Cancel', ko: '취소');
  String get save => tr(zhCn: '保存', zhTw: '儲存', ja: '保存', en: 'Save', ko: '저장');
  String get saving => tr(zhCn: '保存中…', zhTw: '儲存中…', ja: '保存中…', en: 'Saving…', ko: '저장 중…');
  String get saved => tr(zhCn: '已保存', zhTw: '已儲存', ja: '保存しました', en: 'Saved', ko: '저장됨');
  String get saveFailed => tr(zhCn: '保存失败', zhTw: '儲存失敗', ja: '保存に失敗しました', en: 'Save failed', ko: '저장 실패');
  String get edit => tr(zhCn: '编辑', zhTw: '編輯', ja: '編集', en: 'Edit', ko: '편집');
  String get refresh => tr(zhCn: '刷新', zhTw: '重新整理', ja: '更新', en: 'Refresh', ko: '새로고침');
  String get delete => tr(zhCn: '删除', zhTw: '刪除', ja: '削除', en: 'Delete', ko: '삭제');
  String get close => tr(zhCn: '关闭', zhTw: '關閉', ja: '閉じる', en: 'Close', ko: '닫기');
  String get retry => tr(zhCn: '重试', zhTw: '重試', ja: '再試行', en: 'Retry', ko: '재시도');
  String get apply => tr(zhCn: '应用', zhTw: '套用', ja: '適用', en: 'Apply', ko: '적용');
  String get clear => tr(zhCn: '清空', zhTw: '清空', ja: 'クリア', en: 'Clear', ko: '비우기');
  String get add => tr(zhCn: '添加', zhTw: '新增', ja: '追加', en: 'Add', ko: '추가');
  String get loading => tr(zhCn: '加载中…', zhTw: '載入中…', ja: '読み込み中…', en: 'Loading…', ko: '불러오는 중…');
  String get requesting => tr(zhCn: '请求中…', zhTw: '請求中…', ja: 'リクエスト中…', en: 'Requesting…', ko: '요청 중…');
  String get starting => tr(zhCn: '正在启动…', zhTw: '正在啟動…', ja: '起動中…', en: 'Starting…', ko: '시작 중…');
  String get startingServer => tr(zhCn: '正在连接本地服务…', zhTw: '正在連接本機服務…', ja: 'ローカルサーバー起動中…', en: 'Starting local server…', ko: '로컬 서버 시작 중…');
  String get autoLabel => tr(zhCn: '自动', zhTw: '自動', ja: '自動', en: 'Auto', ko: '자동');
  String get exitHint => tr(
        zhCn: '再按一次返回退出应用',
        zhTw: '再按一次返回退出應用程式',
        ja: 'もう一度戻ると終了します',
        en: 'Press back again to exit',
        ko: '뒤로 가기를 한 번 더 누르면 종료됩니다',
      );
  String requestFailed(String err) => tr(
        zhCn: '操作失败: $err',
        zhTw: '操作失敗: $err',
        ja: '操作失敗: $err',
        en: 'Action failed: $err',
        ko: '작업 실패: $err',
      );

  String get playbackFailed => tr(
        zhCn: '无法播放此视频',
        zhTw: '無法播放此影片',
        ja: '動画を再生できません',
        en: 'Unable to play this video',
        ko: '동영상을 재생할 수 없습니다',
      );

  // Showcase & Actress Wall
  String get continueWatching => tr(zhCn: '继续观看', zhTw: '繼續觀看', ja: '続きを見る', en: 'Continue Watching', ko: '이어보기');
  String get removeContinueWatching => tr(zhCn: '从继续观看中移除', zhTw: '從繼續觀看中移除', ja: '「続きを見る」から削除', en: 'Remove from Continue Watching', ko: '이어보기에서 삭제');
  String playbackPart(int n) => tr(zhCn: '第 $n 段', zhTw: '第 $n 段', ja: 'パート $n', en: 'Part $n', ko: '파트 $n');
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
  String get sortAndDisplay => tr(zhCn: '排序与显示', zhTw: '排序與顯示', ja: '並び替えと表示', en: 'Sort & Display', ko: '정렬 및 표시');
  String get sortDesc => tr(zhCn: '降序', zhTw: '降冪', ja: '降順', en: 'Desc', ko: '내림차순');
  String get sortAsc => tr(zhCn: '升序', zhTw: '升冪', ja: '昇順', en: 'Asc', ko: '오름차순');
  String get sortDate => tr(zhCn: '发行日期', zhTw: '發行日期', ja: '発売日', en: 'Release Date', ko: '발매일');
  String get sortAdded => tr(zhCn: '入库时间', zhTw: '入庫時間', ja: '追加日時', en: 'Date Added', ko: '추가일');
  String get sortNumber => tr(zhCn: '番号', zhTw: '番號', ja: '品番', en: 'Number', ko: '품번');
  String get sortTitle => tr(zhCn: '标题', zhTw: '標題', ja: 'タイトル', en: 'Title', ko: '제목');
  String get sortActor => tr(zhCn: '女优', zhTw: '女優', ja: '女優', en: 'Actress', ko: '배우');
  String get sortMaker => tr(zhCn: '片商', zhTw: '片商', ja: 'メーカー', en: 'Maker', ko: '제작사');
  String get sortSize => tr(zhCn: '文件大小', zhTw: '檔案大小', ja: 'サイズ', en: 'File Size', ko: '크기');
  String get sortRandom => tr(zhCn: '随机顺序', zhTw: '隨機順序', ja: 'ランダム', en: 'Random', ko: '무작위');
  String get columnsPerRow => tr(zhCn: '每行列数', zhTw: '每行列數', ja: '列数', en: 'Columns', ko: '열 수');
  String columnsCount(int n) => tr(zhCn: '$n 列', zhTw: '$n 列', ja: '$n列', en: '${n}x', ko: '$n열');
  String get viewMode => tr(zhCn: '视图模式', zhTw: '檢視模式', ja: '表示モード', en: 'View Mode', ko: '보기 모드');
  String get viewGrid => tr(zhCn: '网格', zhTw: '網格', ja: 'グリッド', en: 'Grid', ko: '그리드');
  String get viewList => tr(zhCn: '列表', zhTw: '清單', ja: 'リスト', en: 'List', ko: '목록');
  String get emptyVideos => tr(
        zhCn: '暂无匹配的影片记录',
        zhTw: '暫無符合的影片記錄',
        ja: '一致する動画がありません',
        en: 'No matching videos',
        ko: '일치하는 동영상이 없습니다',
      );
  String get emptyActresses => tr(
        zhCn: '暂无女优数据',
        zhTw: '暫無女優資料',
        ja: '女優データがありません',
        en: 'No actress data',
        ko: '배우 데이터가 없습니다',
      );
  String get loadLibraryFailed => tr(
        zhCn: '加载片库失败',
        zhTw: '載入片庫失敗',
        ja: 'ライブラリの読み込みに失敗しました',
        en: 'Failed to load library',
        ko: '라이브러리 로드 실패',
      );
  String videosUnit(int n) => tr(zhCn: '$n 部', zhTw: '$n 部', ja: '$n本', en: '$n videos', ko: '$n편');
  String get prevPage => tr(zhCn: '上一页', zhTw: '上一頁', ja: '前へ', en: 'Prev', ko: '이전');
  String get nextPage => tr(zhCn: '下一页', zhTw: '下一頁', ja: '次へ', en: 'Next', ko: '다음');
  String get loadingMore => tr(zhCn: '加载更多…', zhTw: '載入更多…', ja: '読み込み中…', en: 'Loading more…', ko: '더 불러오는 중…');
  String get allLoaded => tr(zhCn: '已加载全部内容', zhTw: '已載入全部內容', ja: 'すべて読み込みました', en: 'All loaded', ko: '모두 불러왔습니다');

  // Actress detail & photo picker
  String get actressDetail => tr(zhCn: '女优资料', zhTw: '女優資料', ja: '女優プロフィール', en: 'Actress Profile', ko: '배우 프로필');
  String get favoriteActress => tr(zhCn: '精选女优', zhTw: '精選女優', ja: 'お気に入り登録', en: 'Favorite', ko: '즐겨찾기 추가');
  String get unfavoriteActress => tr(zhCn: '已精选', zhTw: '已精選', ja: 'お気に入り済み', en: 'Favorited', ko: '즐겨찾기됨');
  String get confirmUnfavoriteActress => tr(
        zhCn: '是否取消精选该女优？这将从本地精选列表移除她。',
        zhTw: '是否取消精選該女優？這會將她從精選列表移除。',
        ja: 'この女優をお気に入りから削除しますか？',
        en: 'Remove this actress from favorites?',
        ko: '이 배우를 즐겨찾기에서 제거할까요?',
      );
  String get addFavoriteActress => tr(zhCn: '添加精选女优', zhTw: '新增精選女優', ja: '女優を追加', en: 'Add Favorite Actress', ko: '즐겨찾기 배우 추가');
  String get actressNameHint => tr(zhCn: '输入女优名字', zhTw: '輸入女優名字', ja: '女優名を入力', en: 'Enter actress name', ko: '배우 이름 입력');
  String get actressAdded => tr(zhCn: '已加入精选女优', zhTw: '已加入精選女優', ja: 'お気に入りに追加しました', en: 'Added to favorites', ko: '즐겨찾기에 추가됨');
  String get actressAlreadyExists => tr(zhCn: '该女优已在精选列表', zhTw: '該女優已在精選列表', ja: 'すでにお気に入り登録済みです', en: 'Already in favorites', ko: '이미 즐겨찾기에 있습니다');
  String get actressRemoved => tr(zhCn: '已移出精选列表', zhTw: '已移出精選列表', ja: 'お気に入りから削除しました', en: 'Removed from favorites', ko: '즐겨찾기에서 제거됨');
  String get changeCoverPhoto => tr(zhCn: '更换封面照片', zhTw: '更換封面照片', ja: '写真を選択', en: 'Change Photo', ko: '사진 변경');
  String get uploadLocalPhoto => tr(zhCn: '上传本地照片', zhTw: '上傳本機照片', ja: 'ローカル画像をアップロード', en: 'Upload Photo', ko: '로컬 사진 업로드');
  String get nextPhotoBatch => tr(zhCn: '换一批', zhTw: '換一批', ja: '他の候補', en: 'Next Batch', ko: '다른 후보');
  String get viewActressVideos => tr(zhCn: '查看全部影片', zhTw: '查看全部影片', ja: '出演作を見る', en: 'View Videos', ko: '출연작 보기');
  String get photoCandidatesTitle => tr(zhCn: '选择封面照片', zhTw: '選擇封面照片', ja: '写真候補を選択', en: 'Choose Cover Photo', ko: '커버 사진 선택');
  String get photoCandidatesEmpty => tr(
        zhCn: '暂无更多候选照片，可尝试「换一批」或「上传本地照片」',
        zhTw: '暫無更多候選照片，可嘗試「換一批」或「上傳本機照片」',
        ja: '候補が見つかりません。「他の候補」やアップロードをお試しください',
        en: 'No candidates found. Try Next Batch or Upload.',
        ko: '후보가 없습니다. 다른 후보 또는 업로드를 시도하세요.',
      );
  String get photoReplaced => tr(zhCn: '照片已更换', zhTw: '照片已更換', ja: '写真を変更しました', en: 'Photo updated', ko: '사진이 변경됨');
  String get favoriteFirstHint => tr(
        zhCn: '需先将女优设为精选才能更换封面照片，是否立即添加精选并继续？',
        zhTw: '需先將女優設為精選才能更換封面照片，是否立即加入精選並繼續？',
        ja: '写真を変更するには先にお気に入り登録が必要です。登録して続けますか？',
        en: 'Favorite this actress first to pick a custom cover photo. Continue?',
        ko: '사진을 변경하려면 먼저 즐겨찾기에 추가해야 합니다. 계속할까요?',
      );
  String get detectFocal => tr(
        zhCn: '人脸 / 裁切对焦',
        zhTw: '人臉 / 裁切對焦',
        ja: '顔・トリミング',
        en: 'Face / Crop Focus',
        ko: '얼굴 / 크롭 초점',
      );
  String get focalUpdated => tr(zhCn: '对焦位置已更新', zhTw: '對焦位置已更新', ja: 'フォーカスを更新しました', en: 'Focus updated', ko: '초점 업데이트됨');
  String get focalNoFace => tr(zhCn: '未检测到人脸，保留默认构图', zhTw: '未偵測到人臉，保留預設構圖', ja: '顔が検出されませんでした', en: 'No face detected', ko: '얼굴이 감지되지 않음');
  String get focalCropTitle => tr(zhCn: '封面裁剪对焦', zhTw: '封面裁剪對焦', ja: 'カバーフォーカス調整', en: 'Cover Focal Crop', ko: '커버 초점 크롭');
  String get focalDetectLocalBtn => tr(zhCn: '检测人脸位置', zhTw: '偵測人臉位置', ja: '顔位置を検出', en: 'Detect Face', ko: '얼굴 위치 감지');
  String get focalResetBtn => tr(zhCn: '默认右裁', zhTw: '預設右裁', ja: 'デフォルト', en: 'Reset Default', ko: '기본값');
  String get focalSaveBtn => tr(zhCn: '保存焦点', zhTw: '儲存焦點', ja: '保存', en: 'Save Focus', ko: '초점 저장');
  String get focalDragHint => tr(
        zhCn: '在封面上拖动选框或滑块手动微调，也可点“检测人脸位置”自动定位（本地 Python 检测 / 远端 AI）。',
        zhTw: '在封面上拖動選框或滑塊手動微調，也可點「偵測人臉位置」自動定位（本機 Python 偵測 / 遠端 AI）。',
        ja: 'カバー上で枠をドラッグするか「顔位置を検出」で自動位置合わせできます。',
        en: 'Drag the frame on the cover or run Detect Face (local Python or configured AI).',
        ko: '커버에서 프레임을 드래그하거나 얼굴 감지로 자동 위치를 잡으세요.',
      );
  String get focalSavedMsg => tr(zhCn: '封面焦点已保存', zhTw: '封面焦點已儲存', ja: 'カバーフォーカスを保存しました', en: 'Cover focus saved', ko: '커버 초점 저장됨');
  String get focalDisabledHint => tr(
        zhCn: '自动人脸检测已在设置中禁用，请手动拖动调整位置。',
        zhTw: '自動人臉偵測已在設定中停用，請手動拖動調整位置。',
        ja: '自動顔検出は無効になっています。手動で調整してください。',
        en: 'Auto face detection is disabled in Settings; adjust manually.',
        ko: '자동 얼굴 감지가 비활성화되어 있습니다. 수동으로 조정하세요.',
      );
  String get focalStillDetectingHint => tr(
        zhCn: '检测耗时较长仍在后台运行，请稍后重试或手动拖动。',
        zhTw: '偵測耗時較長仍在背景執行，請稍後重試或手動拖動。',
        ja: '検出がタイムアウトしました。しばらくしてから再試行するか手動で調整してください。',
        en: 'Detection timed out; retry shortly or adjust manually.',
        ko: '감지 시간이 초과되었습니다. 수동으로 조정하거나 다시 시도하세요.',
      );
  String get aliases => tr(zhCn: '别名', zhTw: '別名', ja: '別名', en: 'Aliases', ko: '별명');
  String get birthLabel => tr(zhCn: '生日', zhTw: '生日', ja: '生年月日', en: 'Birth', ko: '생년월일');
  String get heightLabel => tr(zhCn: '身高', zhTw: '身高', ja: '身長', en: 'Height', ko: '신장');
  String get cupLabel => tr(zhCn: '罩杯', zhTw: '罩杯', ja: 'カップ', en: 'Cup', ko: '컵');
  String get measurementsLabel => tr(zhCn: '三围', zhTw: '三圍', ja: 'スリーサイズ', en: 'B/W/H', ko: '신체 사이즈');
  String get hometownLabel => tr(zhCn: '出身地', zhTw: '出身地', ja: '出身地', en: 'Hometown', ko: '출신');
  String get hobbyLabel => tr(zhCn: '兴趣', zhTw: '興趣', ja: '趣味', en: 'Hobby', ko: '취미');

  // Video detail & metadata
  String get numberLabel => tr(zhCn: '番号', zhTw: '番號', ja: '品番', en: 'Number', ko: '품번');
  String get releaseLabel => tr(zhCn: '发行', zhTw: '發行', ja: '発売日', en: 'Released', ko: '발매일');
  String get durationLabel => tr(zhCn: '时长', zhTw: '時長', ja: '収録時間', en: 'Duration', ko: '재생 시간');
  String get makerLabel => tr(zhCn: '片商', zhTw: '片商', ja: 'メーカー', en: 'Maker', ko: '제작사');
  String get directorLabel => tr(zhCn: '导演', zhTw: '導演', ja: '監督', en: 'Director', ko: '감독');
  String get seriesLabel => tr(zhCn: '系列', zhTw: '系列', ja: 'シリーズ', en: 'Series', ko: '시리즈');
  String get labelLabel => tr(zhCn: '厂牌', zhTw: '廠牌', ja: 'レーベル', en: 'Label', ko: '레이블');
  String get sizeLabel => tr(zhCn: '大小', zhTw: '大小', ja: 'サイズ', en: 'Size', ko: '용량');
  String get partsLabel => tr(zhCn: '分段', zhTw: '分段', ja: 'パート', en: 'Parts', ko: '파트');
  String get tagsLabel => tr(zhCn: '标签', zhTw: '標籤', ja: 'タグ', en: 'Tags', ko: '태그');
  String get plot => tr(zhCn: '简介', zhTw: '簡介', ja: 'あらすじ', en: 'Synopsis', ko: '줄거리');
  String get emptyPlot => tr(zhCn: '暂无简介', zhTw: '暫無簡介', ja: 'あらすじはありません', en: 'No synopsis', ko: '줄거리 없음');
  String get addPlotManually => tr(zhCn: '手动添加简介', zhTw: '手動新增簡介', ja: 'あらすじを入力', en: 'Add synopsis', ko: '줄거리 직접 입력');
  String get plotInputHint => tr(zhCn: '输入简介内容…', zhTw: '輸入簡介內容…', ja: 'あらすじを入力…', en: 'Enter synopsis…', ko: '줄거리 입력…');
  String get editTitleLabel => tr(zhCn: '编辑标题', zhTw: '編輯標題', ja: 'タイトル編集', en: 'Edit Title', ko: '제목 편집');
  String get refetchPlot => tr(zhCn: '重新获取', zhTw: '重新取得', ja: '再取得', en: 'Refetch', ko: '다시 가져오기');
  String refetchPlotSuccess(String src) => src.isNotEmpty
      ? tr(zhCn: '已从 $src 重新获取简介', zhTw: '已從 $src 重新取得簡介', ja: '$src から再取得しました', en: 'Fetched synopsis from $src', ko: '$src에서 줄거리를 가져옴')
      : tr(zhCn: '已重新获取简介', zhTw: '已重新取得簡介', ja: 'あらすじを再取得しました', en: 'Synopsis refetched', ko: '줄거리를 다시 가져옴');
  String get refetchPlotEmpty => tr(zhCn: '未获取到简介', zhTw: '未取得到簡介', ja: 'あらすじが見つかりません', en: 'No synopsis found', ko: '줄거리를 찾지 못했습니다');
  String get translateAi => tr(zhCn: 'AI 翻译', zhTw: 'AI 翻譯', ja: 'AI 翻訳', en: 'AI Translate', ko: 'AI 번역');
  String get translateFailed => tr(zhCn: '翻译失败', zhTw: '翻譯失敗', ja: '翻訳失敗', en: 'Translation failed', ko: '번역 실패');
  String get aiAutoTag => tr(zhCn: 'AI 打标签', zhTw: 'AI 標籤', ja: 'AI タグ付け', en: 'AI Tags', ko: 'AI 태그');
  String get sampleImages => tr(zhCn: '剧照', zhTw: '劇照', ja: 'サンプル画像', en: 'Samples', ko: '샘플 이미지');
  String get fetchSamples => tr(zhCn: '补抓剧照', zhTw: '補抓劇照', ja: 'サンプル取得', en: 'Fetch Samples', ko: '샘플 가져오기');
  String get samplesFetched => tr(zhCn: '剧照已更新', zhTw: '劇照已更新', ja: 'サンプル画像を更新しました', en: 'Samples updated', ko: '샘플 이미지 업데이트됨');
  String get showOriginal => tr(zhCn: '显示原文', zhTw: '顯示原文', ja: '原文を表示', en: 'Original', ko: '원문 보기');
  String get showTranslated => tr(zhCn: '显示译文', zhTw: '顯示譯文', ja: '訳文を表示', en: 'Translated', ko: '번역 보기');
  String get similarVideos => tr(zhCn: '相似推荐', zhTw: '相似推薦', ja: '類似作品', en: 'Similar', ko: '비슷한 작품');
  String get videoNotInLibrary => tr(zhCn: '该视频当前未在可见片库目录内', zhTw: '該影片目前不在可見片庫目錄內', ja: 'この動画はライブラリ内に見つかりません', en: 'Video is not in current library', ko: '현재 라이브러리에 없는 동영상입니다');
  String get playVideo => tr(zhCn: '播放影片', zhTw: '播放影片', ja: '再生', en: 'Play', ko: '재생');
  String get builtinPlayer => tr(zhCn: '内置播放器', zhTw: '內建播放器', ja: '内蔵プレーヤー', en: 'Built-in Player', ko: '내장 플레이어');
  String get externalPlayer => tr(zhCn: '外部播放器', zhTw: '外部播放器', ja: '外部プレーヤー', en: 'External Player', ko: '외부 플레이어');
  String get rescrape => tr(zhCn: '重刮元数据', zhTw: '重刮中繼資料', ja: '再スクレイプ', en: 'Rescrape', ko: '재스크랩');
  String rescrapeFieldsHint(String video) => tr(
        zhCn: '只替换「$video」中选了来源的项目，跳过的项目保留原值。',
        zhTw: '只取代「$video」中選了來源的項目，略過的項目保留原值。',
        ja: '「$video」で取得元を選んだ項目だけを置き換えます。スキップした項目は保持されます。',
        en: 'Replace only the fields you select for “$video”. Skipped fields keep their current values.',
        ko: '“$video”에서 소스를 선택한 항목만 교체합니다. 건너뛴 항목은 기존 값을 유지합니다.',
      );
  String get replaceSelectedFields => tr(zhCn: '替换所选项', zhTw: '取代所選項目', ja: '選択した項目を置き換える', en: 'Replace Selected Fields', ko: '선택한 항목 교체');
  String rescrapeSummary(int replaced, int failed, int skipped) => tr(
        zhCn: '已更新 $replaced 项，失败 $failed 项，跳过 $skipped 项',
        zhTw: '已更新 $replaced 項，失敗 $failed 項，略過 $skipped 項',
        ja: '更新 $replaced 件、失敗 $failed 件、スキップ $skipped 件',
        en: '$replaced updated, $failed failed, $skipped skipped',
        ko: '$replaced개 업데이트, $failed개 실패, $skipped개 건너뜀',
      );
  String get addTag => tr(zhCn: '添加标签', zhTw: '新增標籤', ja: 'タグ追加', en: 'Add tag', ko: '태그 추가');
  String get addUserTagTitle => tr(zhCn: '添加个人标签', zhTw: '新增個人標籤', ja: 'カスタムタグを追加', en: 'Add Personal Tag', ko: '개인 태그 추가');
  String get tagNameHint => tr(zhCn: '输入标签名称', zhTw: '輸入標籤名稱', ja: 'タグ名を入力', en: 'Enter tag name', ko: '태그 이름 입력');
  String get removeFromDb => tr(zhCn: '移出片库索引', zhTw: '移出片庫索引', ja: 'ライブラリから削除', en: 'Remove from library', ko: '라이브러리에서 제거');
  String get removeFromDbConfirm => tr(
        zhCn: '仅从本地索引数据库中移除此记录，不会删除视频和封面文件。',
        zhTw: '僅從本機索引資料庫移除此記錄，不會刪除影片與封面檔案。',
        ja: 'ローカルインデックスから削除します。動画・画像ファイルは削除されません。',
        en: 'Removes entry from local database only. Video and image files remain on disk.',
        ko: '로컬 인덱스에서만 제거되며 동영상 및 커버 파일은 삭제되지 않습니다.',
      );
  String get confirmRemove => tr(zhCn: '确认移出', zhTw: '確認移出', ja: '削除する', en: 'Remove', ko: '제거');

  // Search
  String get searchQueryHint => tr(
        zhCn: '搜索番号、女优或关键字…',
        zhTw: '搜尋番號、女優或關鍵字…',
        ja: '品番・女優・キーワードを検索…',
        en: 'Search number, actress, or keyword…',
        ko: '품번, 배우 또는 키워드 검색…',
      );
  String get backToSearchHome => tr(
        zhCn: '返回搜索主页',
        zhTw: '返回搜尋主頁',
        ja: '検索トップへ',
        en: 'Back to Search Home',
        ko: '검색 홈으로',
      );
  String get batchSearch => tr(zhCn: '批量搜番', zhTw: '批次搜番', ja: '一括検索', en: 'Batch Search', ko: '일괄 검색');
  String get batchSearchHint => tr(
        zhCn: '每行或用逗号/空格输入多个番号（最多 50 个）',
        zhTw: '每行或用逗號/空格輸入多個番號（最多 50 個）',
        ja: '複数の品番を改行またはコンマ区切りで入力（最大50件）',
        en: 'Enter up to 50 numbers separated by spaces, commas, or newlines',
        ko: '쉼표/줄바꿈으로 최대 50개 품번 입력',
      );
  String get startBatchSearch => tr(zhCn: '开始批量搜索', zhTw: '開始批次搜尋', ja: '一括検索開始', en: 'Search All', ko: '일괄 검색 시작');
  String get imageSearch => tr(zhCn: '以图搜番', zhTw: '以圖搜番', ja: '画像検索', en: 'Image Search', ko: '이미지 검색');
  String get imageSearching => tr(zhCn: '正在以图搜番…', zhTw: '正在以圖搜番…', ja: '画像で検索中…', en: 'Searching by image…', ko: '이미지로 검색 중…');
  String get imageSearchCandidates => tr(zhCn: '以图搜番候选结果', zhTw: '以圖搜番候選結果', ja: '画像検索候補', en: 'Image Search Matches', ko: '이미지 검색 후보');
  String get imageSearchNoMatch => tr(zhCn: '未识别到匹配番号', zhTw: '未辨識到符合番號', ja: '一致する品番が見つかりません', en: 'No matching number found', ko: '일치하는 품번이 없습니다');
  String matchConfidence(String pct, bool inLib) => inLib
      ? tr(zhCn: '匹配度 $pct% · 已入库', zhTw: '符合度 $pct% · 已入庫', ja: '一致度 $pct% · ライブラリ済', en: '$pct% match · In Library', ko: '일치율 $pct% · 보유 중')
      : tr(zhCn: '匹配度 $pct%', zhTw: '符合度 $pct%', ja: '一致度 $pct%', en: '$pct% match', ko: '일치율 $pct%');
  String wishlistCount(int n) => tr(zhCn: '待看书签 ($n)', zhTw: '待看書籤 ($n)', ja: 'ブックマーク ($n)', en: 'Wishlist ($n)', ko: '북마크 ($n)');
  String get emptyWishlist => tr(zhCn: '书签列表为空', zhTw: '書籤清單為空', ja: 'ブックマークは空です', en: 'Wishlist is empty', ko: '북마크가 비어 있습니다');
  String get inLibraryBadge => tr(zhCn: '已入库', zhTw: '已入庫', ja: 'ライブラリ済', en: 'In Library', ko: '보유 중');
  String get playLabel => tr(zhCn: '播放', zhTw: '播放', ja: '再生', en: 'Play', ko: '재생');
  String get wishlisted => tr(zhCn: '已收藏', zhTw: '已收藏', ja: '登録済み', en: 'Saved', ko: '저장됨');
  String get addWishlist => tr(zhCn: '加入书签', zhTw: '加入書籤', ja: 'ブックマーク', en: 'Wishlist', ko: '북마크 추가');
  String get alreadyOwnedHint => tr(zhCn: '本地片库已有此影片', zhTw: '本機片庫已有此影片', ja: 'すでにライブラリに存在します', en: 'Already in local library', ko: '이미 로컬 라이브러리에 있음');
  String get viewInLibrary => tr(zhCn: '在片库查看详情', zhTw: '在片庫查看詳情', ja: 'ライブラリで詳細を見る', en: 'Open in Library', ko: '라이브러리에서 보기');
  String get openOriginalUrl => tr(zhCn: '打开原站页面', zhTw: '開啟原站頁面', ja: '元ページを開く', en: 'Open Source Page', ko: '원본 페이지 열기');
  String get makerCapsulesTitle => tr(zhCn: '片商新作速览', zhTw: '片商新作速覽', ja: 'メーカー新作', en: 'Maker Releases', ko: '제작사 신작');
  String get recentActressesLabel => tr(zhCn: '常收女优新作', zhTw: '常收女優新作', ja: 'お気に入り女優の新作', en: 'Recent Favorite Actresses', ko: '즐겨찾기 배우 신작');
  String favoriteFilesTitle(int n) => tr(zhCn: '待整理文件 ($n)', zhTw: '待整理檔案 ($n)', ja: '未整理ファイル ($n)', en: 'Pending Files ($n)', ko: '정리 대기 파일 ($n)');
  String get noFavoriteFiles => tr(
        zhCn: '暂无待整理文件（可在设置中配置待整理文件夹）',
        zhTw: '暫無待整理檔案（可在設定中設定待整理資料夾）',
        ja: '未整理ファイルはありません（設定でフォルダを指定できます）',
        en: 'No pending files (configure folder in Settings)',
        ko: '대기 파일 없음 (설정에서 폴더 지정 가능)',
      );
  String guessedNumber(String num) => tr(zhCn: '推测番号: $num', zhTw: '推測番號: $num', ja: '推測品番: $num', en: 'Detected: $num', ko: '추정 품번: $num');
  String get organizeBtn => tr(zhCn: '整理', zhTw: '整理', ja: '整理', en: 'Organize', ko: '정리');
  String get scrapeOrganizeTitle => tr(zhCn: '刮削整理文件', zhTw: '刮削整理檔案', ja: 'メタデータ整理', en: 'Scrape & Organize', ko: '스크랩 및 정리');
  String get detectedNumberField => tr(zhCn: '识别番号', zhTw: '辨識番號', ja: '品番', en: 'Number', ko: '품번');
  String get startOrganize => tr(zhCn: '开始整理', zhTw: '開始整理', ja: '整理開始', en: 'Organize', ko: '정리 시작');
  String get organizeCompleted => tr(zhCn: '整理完成', zhTw: '整理完成', ja: '整理完了', en: 'Organized', ko: '정리 완료');
  String get emptySearchResults => tr(zhCn: '未找到相关结果', zhTw: '未找到相關結果', ja: '結果が見つかりません', en: 'No search results', ko: '검색 결과가 없습니다');
  String searchResultDetailTitle(int idx, int total) => tr(
        zhCn: '搜索结果 ($idx / $total)',
        zhTw: '搜尋結果 ($idx / $total)',
        ja: '検索結果 ($idx / $total)',
        en: 'Result ($idx / $total)',
        ko: '검색 결과 ($idx / $total)',
      );

  // Scanner
  String libraryTotalHeader(int n) => tr(
        zhCn: '当前片库 $n 部影片',
        zhTw: '目前片庫 $n 部影片',
        ja: 'ライブラリ合計 $n 本',
        en: 'Library: $n videos',
        ko: '라이브러리 총 $n편',
      );
  String get scanLibrary => tr(zhCn: '扫描片库', zhTw: '掃描片庫', ja: 'スキャン開始', en: 'Scan Library', ko: '라이브러리 스캔');
  String get stopTask => tr(zhCn: '停止任务', zhTw: '停止任務', ja: 'タスク停止', en: 'Stop Task', ko: '작업 중지');
  String get metadataBackfill => tr(zhCn: '元数据补全', zhTw: '中繼資料補全', ja: 'メタデータ補完', en: 'Metadata Backfill', ko: '메타데이터 채우기');
  String get metadataFieldsDescription => tr(zhCn: '封面、简介、剧照和标签', zhTw: '封面、簡介、劇照和標籤', ja: 'カバー、あらすじ、サンプル画像、タグ', en: 'Cover, synopsis, samples and tags', ko: '커버, 줄거리, 샘플 이미지, 태그');
  String get metadataBackfillHint => tr(zhCn: '选择每项缺失数据的来源，或跳过该项。', zhTw: '選擇每項缺失資料的來源，或略過該項。', ja: '不足している項目ごとに取得元を選ぶか、スキップしてください。', en: 'Choose a source for each missing field, or skip it.', ko: '비어 있는 항목마다 소스를 선택하거나 건너뛰세요.');
  String get runMetadataBackfill => tr(zhCn: '一键补全', zhTw: '一鍵補全', ja: '一括補完', en: 'Fill Missing Fields', ko: '누락 항목 채우기');
  String get coverLabel => tr(zhCn: '封面', zhTw: '封面', ja: 'カバー', en: 'Cover', ko: '커버');
  String get skipField => tr(zhCn: '跳过', zhTw: '略過', ja: 'スキップ', en: 'Skip', ko: '건너뛰기');
  String get invalidSourceList => tr(zhCn: '来源列表无效', zhTw: '來源清單無效', ja: '取得元の一覧が無効です', en: 'Invalid source list', ko: '소스 목록이 올바르지 않습니다');
  String get noMetadataSources => tr(zhCn: '当前设置中没有可用来源', zhTw: '目前設定中沒有可用來源', ja: '現在の設定で利用できる取得元がありません', en: 'No sources are available with the current settings', ko: '현재 설정에서 사용할 수 있는 소스가 없습니다');
  String get noPendingPlots => tr(zhCn: '没有待翻译的简介', zhTw: '沒有待翻譯的簡介', ja: '翻訳待ちのあらすじはありません', en: 'No plots are waiting for translation', ko: '번역할 줄거리가 없습니다');
  String get translatePendingPlots => tr(zhCn: '翻译已补全简介', zhTw: '翻譯已補全簡介', ja: '取得済みあらすじを翻訳', en: 'Translate Pending Plots', ko: '가져온 줄거리 번역');
  String get backfillTitles => tr(zhCn: '翻译标题', zhTw: '翻譯標題', ja: 'タイトル翻訳', en: 'Translate Titles', ko: '제목 번역');
  String get backfillJellyfin => tr(zhCn: '补齐 Jellyfin 封面', zhTw: '補齊 Jellyfin 封面', ja: 'Jellyfin 画像補完', en: 'Jellyfin Art', ko: 'Jellyfin 이미지');
  String get backfillJellyfinDesc => tr(zhCn: '生成 -poster / -fanart 媒体服务器图像', zhTw: '產生 -poster / -fanart 媒體伺服器圖像', ja: 'poster / fanart 画像を生成', en: 'Generate -poster / -fanart media art', ko: '미디어 서버용 poster/fanart 생성');
  String get advancedMaintenance => tr(zhCn: '高级维护与别名管理', zhTw: '進階維護與別名管理', ja: 'メンテナンスと別名管理', en: 'Maintenance & Aliases', ko: '유지보수 및 별명 관리');
  String get renameNormalize => tr(zhCn: '文件命名整理', zhTw: '檔案命名整理', ja: 'リネーム整理', en: 'Normalize Names', ko: '파일명 정리');
  String get renameNormalizeDesc => tr(zhCn: '预览并规范化视频文件命名', zhTw: '預覽並規範化影片檔案命名', ja: 'ファイル名を一括正規化', en: 'Preview and standardize filenames', ko: '파일명 일괄 정규화');
  String renamePreviewTitle(int n) => tr(zhCn: '文件名整理预览 ($n 项待修改)', zhTw: '檔名整理預覽 ($n 項待修改)', ja: 'リネームプレビュー ($n 件)', en: 'Rename Preview ($n items)', ko: '이름 변경 미리보기 ($n건)');
  String get renameAllClean => tr(zhCn: '所有文件命名均已规范', zhTw: '所有檔案命名均已規範', ja: 'すべて正規化されています', en: 'All filenames are already normalized', ko: '모든 파일명이 정규화되어 있습니다');
  String get renameExecute => tr(zhCn: '确认执行重命名', zhTw: '確認執行重新命名', ja: 'リネームを実行', en: 'Execute Rename', ko: '이름 변경 실행');
  String get renameCompleted => tr(zhCn: '批量命名整理完成', zhTw: '批次命名整理完成', ja: 'リネーム完了', en: 'Batch rename completed', ko: '일괄 이름 변경 완료');
  String get collectionAnalysis => tr(zhCn: '片库健康分析与番号修复', zhTw: '片庫健康分析與番號修復', ja: 'コレクション分析・品番修正', en: 'Library Health & Number Fix', ko: '컬렉션 분석 및 품번 복구');
  String get actressAliasesManage => tr(zhCn: '女优别名管理', zhTw: '女優別名管理', ja: '女優別名管理', en: 'Actress Aliases', ko: '배우 별명 관리');
  String get tagAliasesManage => tr(zhCn: '标签别名管理', zhTw: '標籤別名管理', ja: 'タグ別名管理', en: 'Tag Aliases', ko: '태그 별명 관리');
  String get clearCache => tr(zhCn: '清空片库索引', zhTw: '清空片庫索引', ja: 'キャッシュ削除', en: 'Clear Index', ko: '인덱스 초기화');
  String get clearCacheDesc => tr(zhCn: '清空 SQLite 索引（不删物理文件）', zhTw: '清空 SQLite 索引（不刪實體檔案）', ja: 'SQLite インデックスのみ削除', en: 'Clear SQLite index (keeps files)', ko: 'SQLite 인덱스만 비움');
  String get clearCacheConfirm => tr(
        zhCn: '清空本地 SQLite 索引后需重新扫描片库，不会删除您的视频或 NFO 文件。',
        zhTw: '清空本機 SQLite 索引後需重新掃描片庫，不會刪除您的影片或 NFO 檔案。',
        ja: 'ローカル DB のみを削除します。動画や NFO ファイルは削除されません。',
        en: 'Clears the local SQLite database only. Re-scan needed. Files are untouched.',
        ko: '로컬 SQLite DB만 삭제되며 파일은 유지됩니다. 다시 스캔해야 합니다.',
      );
  String get taskDone => tr(zhCn: '任务完成', zhTw: '任務完成', ja: 'タスク完了', en: 'Task completed', ko: '작업 완료');
  String get taskFailed => tr(zhCn: '执行失败', zhTw: '執行失敗', ja: '実行失敗', en: 'Task failed', ko: '실행 실패');
  String get taskAborted => tr(zhCn: '■ 用户已请求中止任务', zhTw: '■ 使用者已請求中止任務', ja: '■ ユーザーにより中止されました', en: '■ Cancelled by user', ko: '■ 사용자에 의해 중지됨');
  String get taskCancelled => tr(
    zhCn: '任务已取消',
    zhTw: '任務已取消',
    ja: 'タスクはキャンセルされました',
    en: 'Task cancelled',
    ko: '작업이 취소되었습니다',
  );
  String get taskStreamInterrupted => tr(
    zhCn: '任务结束前连接已断开',
    zhTw: '任務結束前連線已中斷',
    ja: 'タスクの終了前に接続が切断されました',
    en: 'Connection closed before the task reported a result',
    ko: '작업 결과를 받기 전에 연결이 끊겼습니다',
  );

  // Insights
  String get insightsVideos => tr(zhCn: '影片', zhTw: '影片', ja: '動画', en: 'Videos', ko: '동영상');
  String get insightsYears => tr(zhCn: '年份', zhTw: '年份', ja: '年', en: 'Years', ko: '연도');
  String get insightsActresses => tr(zhCn: '女优', zhTw: '女優', ja: '女優', en: 'Actresses', ko: '배우');
  String get insightsMakers => tr(zhCn: '片商', zhTw: '片商', ja: 'メーカー', en: 'Makers', ko: '제작사');
  String get insightsYearDistribution => tr(zhCn: '发行年份分布', zhTw: '發行年份分布', ja: '発売年分布', en: 'Release Year Distribution', ko: '발매 연도 분포');
  String get insightsMakerTop => tr(zhCn: '片商分布 Top 8', zhTw: '片商分布 Top 8', ja: 'メーカー分布 Top 8', en: 'Top 8 Makers', ko: '상위 8 제작사');
  String get insightsActressBoard => tr(zhCn: '女优作品榜 (点击跳转片库)', zhTw: '女優作品榜 (點擊跳轉片庫)', ja: '女優ランキング (タップで絞り込み)', en: 'Top Actresses (Tap to Filter)', ko: '배우 랭킹 (탭하여 이동)');
  String insightsTagsTop(int n) => tr(zhCn: '高频标签 Top $n (点击筛选)', zhTw: '高頻標籤 Top $n (點擊篩選)', ja: '頻出タグ Top $n', en: 'Top $n Tags (Tap to Filter)', ko: '인기 태그 Top $n');
  String get insightsEmpty => tr(zhCn: '暂无可分析的片库数据', zhTw: '暫無可分析的片庫資料', ja: '分析可能なデータがありません', en: 'No library records yet', ko: '분석할 데이터가 없습니다');

  // Browse directory picker
  String get chooseFolder => tr(zhCn: '选择目录', zhTw: '選擇目錄', ja: 'フォルダ選択', en: 'Select Folder', ko: '폴더 선택');
  String get parentFolder => tr(zhCn: '上一层', zhTw: '上一層', ja: '上の階層', en: 'Up', ko: '상위 폴더');
  String get backToRoot => tr(zhCn: '返回根目录', zhTw: '返回根目錄', ja: 'ルートへ戻る', en: 'Back to Root', ko: '루트로');
  String get selectCurrentFolder => tr(zhCn: '选择当前目录', zhTw: '選擇目前目錄', ja: 'このフォルダを選択', en: 'Select Current Folder', ko: '현재 폴더 선택');

  // Settings sections & fields
  String get secAppearance => tr(zhCn: '外观与通用', zhTw: '外觀與通用', ja: '外観と一般', en: 'Appearance & General', ko: '외관 및 일반');
  String get secGallery => tr(zhCn: '片库目录与展示', zhTw: '片庫目錄與展示', ja: 'ライブラリと表示', en: 'Library & Display', ko: '라이브러리 및 표시');
  String get secScraper => tr(zhCn: '刮削与文件命名', zhTw: '刮削與檔案命名', ja: 'スクレイプと命名規則', en: 'Scraping & Naming', ko: '스크랩 및 파일명 규칙');
  String get secSearchSources => tr(zhCn: '搜索、代理与来源', zhTw: '搜尋、代理與來源', ja: '検索・プロキシ・ソース', en: 'Search, Proxy & Sources', ko: '검색, 프록시 및 소스');
  String get secAiServices => tr(zhCn: 'AI 服务与人脸识别', zhTw: 'AI 服務與人臉識別', ja: 'AI サービスと顔認識', en: 'AI Services & Face Focus', ko: 'AI 서비스 및 얼굴 인식');
  String get secBackupAbout => tr(zhCn: '备份、重置与关于', zhTw: '備份、重置與關於', ja: 'バックアップと情報', en: 'Backup, Reset & About', ko: '백업, 초기화 및 정보');

  String get themeTitle => tr(zhCn: '界面主题', zhTw: '介面主題', ja: 'テーマ', en: 'Theme', ko: '테마');
  String get themeDim => tr(zhCn: '影院灰', zhTw: '影院灰', ja: 'ディム', en: 'Dim', ko: '딤');
  String get themeDark => tr(zhCn: '纯黑', zhTw: '純黑', ja: 'ダーク', en: 'Dark', ko: '다크');
  String get themeLight => tr(zhCn: '浅色', zhTw: '淺色', ja: 'ライト', en: 'Light', ko: '라이트');
  String get languageTitle => tr(zhCn: '界面语言', zhTw: '介面語言', ja: '言語', en: 'Language', ko: '언어');
  String get fontSizeTitle => tr(zhCn: '字体大小', zhTw: '字體大小', ja: '文字サイズ', en: 'Font Size', ko: '글꼴 크기');
  String get defaultPageTitle => tr(zhCn: '默认启动页', zhTw: '預設啟動頁', ja: '起動ページ', en: 'Default Startup Page', ko: '기본 시작 페이지');
  String get autoCheckUpdateTitle => tr(zhCn: '启动时检查更新', zhTw: '啟動時檢查更新', ja: '起動時に更新を確認', en: 'Check Updates on Startup', ko: '시작 시 업데이트 확인');

  String get storagePermissionTitle => tr(zhCn: '所有文件访问权限', zhTw: '所有檔案存取權限', ja: 'すべてのファイルへのアクセス', en: 'All Files Permission', ko: '모든 파일 접근 권한');
  String get granted => tr(zhCn: '已授权', zhTw: '已授權', ja: '許可済み', en: 'Granted', ko: '허용됨');
  String get notGranted => tr(zhCn: '未授权', zhTw: '未授權', ja: '未許可', en: 'Not granted', ko: '허용되지 않음');
  String get safTreeTitle => tr(zhCn: 'SAF 可写目录授权 (SD 卡)', zhTw: 'SAF 可寫目錄授權 (SD 卡)', ja: 'SAF 書き込み許可 (SD カード)', en: 'SAF Writable Folder (SD Card)', ko: 'SAF 쓰기 폴더 권한 (SD 카드)');
  String get safNotConfigured => tr(zhCn: '未配置（仅 SD 卡写回时需要）', zhTw: '未設定（僅 SD 卡寫回時需要）', ja: '未設定（SDカード書き込み時のみ必要）', en: 'Not configured (only needed for SD card writes)', ko: '미설정 (SD 카드 쓰기 시에만 필요)');
  String get authorize => tr(zhCn: '授权', zhTw: '授權', ja: '許可', en: 'Authorize', ko: '권한 부여');
  String get readonlySource => tr(zhCn: '只读来源 (Media Server 模式)', zhTw: '唯讀來源 (Media Server 模式)', ja: '読み取り専用 (Media Server)', en: 'Read-only source', ko: '읽기 전용 소스');
  String get writableSource => tr(zhCn: '本地可写来源', zhTw: '本機可寫來源', ja: 'ローカル書き込み可', en: 'Writable local source', ko: '로컬 쓰기 가능 소스');
  String get addScanDir => tr(zhCn: '添加扫描目录', zhTw: '新增掃描目錄', ja: 'スキャンフォルダを追加', en: 'Add Library Folder', ko: '스캔 폴더 추가');
  String get outputDirTitle => tr(zhCn: '整理输出目录', zhTw: '整理輸出目錄', ja: '整理先フォルダ', en: 'Output Directory', ko: '정리 출력 폴더');
  String get outputDirHelp => tr(
        zhCn: '留空时使用默认数据目录',
        zhTw: '留空時使用預設資料目錄',
        ja: '空欄の場合は既定のデータフォルダを使用します',
        en: 'Leave blank to use the default data directory',
        ko: '비워 두면 기본 데이터 폴더를 사용합니다',
      );
  String get thumbCacheTitle => tr(zhCn: '本地 WebP 缩略图缓存', zhTw: '本機 WebP 縮圖快取', ja: 'ローカル WebP サムネイルキャッシュ', en: 'Local WebP Thumbnail Cache', ko: '로컬 WebP 썸네일 캐시');
  String get thumbCacheSub => tr(zhCn: '加速封面墙滑动帧率', zhTw: '加速封面牆滑動幀率', ja: 'スクロール性能を向上', en: 'Speeds up grid scrolling', ko: '그리드 스크롤 속도 향상');
  String get coverBadgesTitle => tr(zhCn: '显示封面角标 (字幕 / 分段)', zhTw: '顯示封面角標 (字幕 / 分段)', ja: 'カバーバッジを表示', en: 'Show Cover Badges', ko: '커버 배지 표시');
  String get minVideoSizeTitle => tr(zhCn: '最小视频大小过滤 (MB)', zhTw: '最小影片大小過濾 (MB)', ja: '最小動画サイズ (MB)', en: 'Minimum Video Size (MB)', ko: '최소 동영상 크기 (MB)');
  String get clearThumbCache => tr(zhCn: '清空缩略图缓存', zhTw: '清空縮圖快取', ja: 'サムネイルキャッシュ削除', en: 'Clear Thumbnail Cache', ko: '썸네일 캐시 삭제');
  String get thumbCacheCleared => tr(zhCn: '缩略图缓存已清空', zhTw: '縮圖快取已清空', ja: 'サムネイルキャッシュを削除しました', en: 'Thumbnail cache cleared', ko: '썸네일 캐시가 삭제됨');

  String get createFolderTitle => tr(zhCn: '整理时创建独立文件夹', zhTw: '整理時建立獨立資料夾', ja: '整理時に個別フォルダ作成', en: 'Create Subfolder on Organize', ko: '정리 시 하위 폴더 생성');
  String get folderFormatTitle => tr(zhCn: '目录命名格式', zhTw: '目錄命名格式', ja: 'フォルダ名形式', en: 'Folder Format', ko: '폴더 형식');
  String get folderFormatHelp => tr(zhCn: '例如 {actor}', zhTw: '例如 {actor}', ja: '例 {actor}', en: 'Example {actor}', ko: '예시 {actor}');
  String get filenameFormatTitle => tr(zhCn: '文件命名格式', zhTw: '檔案命名格式', ja: 'ファイル名形式', en: 'Filename Format', ko: '파일명 형식');
  String get filenameFormatHelp => tr(zhCn: '例如 {num} {title}', zhTw: '例如 {num} {title}', ja: '例 {num} {title}', en: 'Example {num} {title}', ko: '예시 {num} {title}');
  String get nfoTitleFormatTitle => tr(zhCn: 'NFO 标题格式', zhTw: 'NFO 標題格式', ja: 'NFO タイトル形式', en: 'NFO Title Format', ko: 'NFO 제목 형식');
  String get coverFilenameTitle => tr(zhCn: '封面文件名', zhTw: '封面檔案名稱', ja: 'カバーファイル名', en: 'Cover Filename', ko: '커버 파일명');
  String get downloadCoverTitle => tr(zhCn: '下载封面图片', zhTw: '下載封面圖片', ja: 'カバー画像をダウンロード', en: 'Download Cover', ko: '커버 다운로드');
  String get createNfoTitle => tr(zhCn: '生成 NFO 元数据文件', zhTw: '產生 NFO 中繼資料檔案', ja: 'NFO ファイルを作成', en: 'Create NFO Metadata', ko: 'NFO 파일 생성');
  String get downloadSamplesTitle => tr(zhCn: '同时下载剧照', zhTw: '同時下載劇照', ja: 'サンプル画像もダウンロード', en: 'Download Sample Images', ko: '샘플 이미지도 다운로드');
  String get externalManagerTitle => tr(zhCn: '外部媒体服务器模式', zhTw: '外部媒體伺服器模式', ja: '外部メディアサーバー', en: 'External Media Manager', ko: '외부 미디어 관리자');
  String get maxTitleLengthTitle => tr(zhCn: '标题最大长度', zhTw: '標題最大長度', ja: 'タイトル最大文字数', en: 'Max Title Length', ko: '최대 제목 길이');
  String get maxFilenameLengthTitle => tr(zhCn: '文件名最大长度', zhTw: '檔名最大長度', ja: 'ファイル名最大文字数', en: 'Max Filename Length', ko: '최대 파일명 길이');
  String get videoExtensionsTitle => tr(zhCn: '视频扩展名', zhTw: '影片副檔名', ja: '対象拡張子', en: 'Video Extensions', ko: '동영상 확장자');
  String get suffixKeywordsTitle => tr(zhCn: '分段 / 版本后缀', zhTw: '分段 / 版本後綴', ja: 'サフィックスキーワード', en: 'Suffix Keywords', ko: '접미사 키워드');
  String get commaSeparatedHelp => tr(zhCn: '多项用逗号分隔', zhTw: '多個項目以逗號分隔', ja: '複数の項目はカンマ区切り', en: 'Separate multiple entries with commas', ko: '여러 항목은 쉼표로 구분');

  String get uncensoredModeTitle => tr(zhCn: '无码优先模式', zhTw: '無碼優先模式', ja: '無修正優先モード', en: 'Uncensored Priority Mode', ko: '노모 우선 모드');
  String get proxyUrlTitle => tr(zhCn: 'HTTP / SOCKS5 代理地址', zhTw: 'HTTP / SOCKS5 代理位址', ja: 'HTTP / SOCKS5 プロキシ URL', en: 'Proxy URL', ko: '프록시 URL');
  String get proxyScopeTitle => tr(zhCn: '代理作用域', zhTw: '代理作用域', ja: 'プロキシ適用範囲', en: 'Proxy Scope', ko: '프록시 범위');
  String get favoriteFolderTitle => tr(zhCn: '待整理收藏文件夹', zhTw: '待整理收藏資料夾', ja: '整理待ちフォルダ', en: 'Pending Scrape Folder', ko: '정리 대기 폴더');
  String get testSources => tr(zhCn: '测试连通性', zhTw: '測試連線', ja: '接続テスト', en: 'Test Sources', ko: '소스 연결 테스트');
  String get sourceCapHint => tr(zhCn: '长按拖动排序，常规启用来源上限 10 个', zhTw: '長按拖動排序，常規啟用來源上限 10 個', ja: '長押しで並替、通常有効ソース上限 10 件', en: 'Drag to reorder (max 10 non-manual sources)', ko: '길게 눌러 정렬 (최대 10개)');
  String get metatubeSectionTitle => tr(zhCn: 'Metatube 远端服务', zhTw: 'Metatube 遠端服務', ja: 'Metatube サーバー', en: 'Metatube Server', ko: 'Metatube 서버');
  String get sourceLinksTitle => tr(zhCn: '外链来源显示开关', zhTw: '外鏈來源顯示開關', ja: '外部リンク表示', en: 'Source External Links', ko: '외부 링크 표시');

  String get enableAiTranslateTitle => tr(zhCn: '启用 AI 翻译标题 / 简介', zhTw: '啟用 AI 翻譯標題 / 簡介', ja: 'AI 翻訳を有効にする', en: 'Enable AI Translation', ko: 'AI 번역 사용');
  String get translateProviderTitle => tr(zhCn: '翻译提供方', zhTw: '翻譯提供方', ja: '翻訳プロバイダー', en: 'Provider', ko: '번역 제공자');
  String get serviceUrlLabel => tr(zhCn: '服务地址', zhTw: '服務位址', ja: 'サービス URL', en: 'Service URL', ko: '서비스 URL');
  String get baseUrlLabel => tr(zhCn: 'API 基础地址', zhTw: 'API 基礎位址', ja: 'API ベース URL', en: 'API Base URL', ko: 'API 기본 URL');
  String get apiKeyLabel => tr(zhCn: 'API 密钥', zhTw: 'API 金鑰', ja: 'API キー', en: 'API Key', ko: 'API 키');
  String get accessTokenLabel => tr(zhCn: '访问令牌', zhTw: '存取權杖', ja: 'アクセストークン', en: 'Access Token', ko: '액세스 토큰');
  String get modelLabel => tr(zhCn: '模型', zhTw: '模型', ja: 'モデル', en: 'Model', ko: '모델');
  String get testConnection => tr(zhCn: '测试连接', zhTw: '測試連線', ja: '接続テスト', en: 'Test Connection', ko: '연결 테스트');
  String get testTranslateBtn => tr(zhCn: '测试翻译', zhTw: '測試翻譯', ja: '翻訳テスト', en: 'Test Translate', ko: '번역 테스트');
  String get fetchModelsBtn => tr(zhCn: '获取模型', zhTw: '取得模型', ja: 'モデル取得', en: 'Fetch Models', ko: '모델 가져오기');
  String get presetsLabel => tr(zhCn: '供应商快速预设', zhTw: '供應商快速預設', ja: 'プロバイダプリセット', en: 'Quick Presets', ko: '빠른 프리셋');
  String get quickModelSelectLabel => tr(zhCn: '可用模型快速选取', zhTw: '可用模型快速選取', ja: 'モデルクイック選択', en: 'Available Models', ko: '모델 빠른 선택');
  String modelsLoadedCount(int count) => tr(
        zhCn: '已获取 $count 个模型（点击下方即可填入）',
        zhTw: '已取得 $count 個模型（點擊下方即可填入）',
        ja: '$count 件のモデルを取得しました（タップして選択）',
        en: 'Loaded $count models (tap below to select)',
        ko: '$count개 모델 로드됨 (탭하여 선택)',
      );
  String get modelsFetchFailed => tr(zhCn: '连接或获取模型失败', zhTw: '連線或取得模型失敗', ja: 'モデル取得に失敗しました', en: 'Failed to fetch models', ko: '모델 가져오기 실패');
  String get connectSuccess => tr(zhCn: '连接成功', zhTw: '連線成功', ja: '接続成功', en: 'Connection succeeded', ko: '연결 성공');
  String get connectFailed => tr(zhCn: '连接失败', zhTw: '連線失敗', ja: '接続失敗', en: 'Connection failed', ko: '연결 실패');
  String get serviceTypeLabel => tr(zhCn: '服务类型', zhTw: '服務類型', ja: 'サービス種別', en: 'Service Type', ko: '서비스 유형');
  String get legacyEndpointType => tr(zhCn: '标准接口 (/v1/...)', zhTw: '標準介面 (/v1/...)', ja: '標準エンドポイント', en: 'Standard Endpoint', ko: '표준 엔드포인트');
  String get qwenEmbeddingType => tr(zhCn: '阿里云百炼 (Qwen Embedding)', zhTw: '阿里雲百煉 (Qwen Embedding)', ja: 'Alibaba Cloud Qwen Embedding', en: 'Alibaba Qwen Embedding', ko: 'Alibaba Qwen Embedding');
  String get openaiVisionType => tr(zhCn: 'OpenAI 兼容视觉模型 (Vision)', zhTw: 'OpenAI 相容視覺模型 (Vision)', ja: 'OpenAI互換 Vision VLM', en: 'OpenAI-Compatible Vision VLM', ko: 'OpenAI 호환 Vision VLM');
  String get providerPlaceholder => tr(zhCn: '请选择提供方', zhTw: '請選擇提供方', ja: 'プロバイダーを選択', en: 'Select provider', ko: '제공자 선택');
  String get focalAutoEnabledTitle => tr(zhCn: '禁用自动人脸对焦检测', zhTw: '停用自動人臉對焦偵測', ja: '自動顔検出を無効化', en: 'Disable Auto Face Focus', ko: '자동 얼굴 초점 끄기');
  String get aiImageSimilarTitle => tr(zhCn: 'AI 封面相似度服务', zhTw: 'AI 封面相似度服務', ja: 'AI 類似画像サービス', en: 'AI Image Similarity', ko: 'AI 이미지 유사도');
  String get aiFacesTitle => tr(zhCn: 'AI 远端人脸识别', zhTw: 'AI 遠端人臉識別', ja: 'AI 顔検出エンドポイント', en: 'AI Remote Face Detection', ko: 'AI 원격 얼굴 인식');
  String get aiTagsTitle => tr(zhCn: 'AI 视觉自动标签', zhTw: 'AI 視覺自動標籤', ja: 'AI 自動タグ付け', en: 'AI Vision Tagging', ko: 'AI 자동 태깅');

  String get exportDbTitle => tr(zhCn: '导出数据库备份 (ZIP)', zhTw: '匯出資料庫備份 (ZIP)', ja: 'DB バックアップ出力 (ZIP)', en: 'Export Database Backup (ZIP)', ko: 'DB 백업 내보내기 (ZIP)');
  String get importDbTitle => tr(zhCn: '从备份恢复数据库', zhTw: '從備份還原資料庫', ja: 'バックアップから復元', en: 'Restore Database Backup', ko: '백업에서 DB 복원');
  String get resetFactoryTitle => tr(zhCn: '恢复默认设置', zhTw: '恢復預設設定', ja: '設定をリセット', en: 'Reset Settings to Defaults', ko: '설정 초기화');
  String get resetFactoryConfirm => tr(
        zhCn: '确定将 config.json 重置为默认配置吗？不会删除片库数据和视频。',
        zhTw: '確定將 config.json 重置為預設設定嗎？不會刪除片庫資料與影片。',
        ja: '設定を初期状態に戻しますか？ライブラリデータは削除されません。',
        en: 'Reset all settings to factory defaults? Library videos and database stay intact.',
        ko: '모든 설정을 기본값으로 초기화할까요? 동영상과 DB는 유지됩니다.',
      );
  String get switchClassicWebTitle => tr(zhCn: '切换到 Web 经典视图 (排错/备用)', zhTw: '切換到 Web 經典檢視 (排錯/備用)', ja: 'Web ビューに切替 (トラブルシュート)', en: 'Switch to Classic WebView (Troubleshooting)', ko: '클래식 웹 뷰로 전환');
  String get switchClassicWebSub => tr(
        zhCn: '打开原 WebView 界面进行交叉比对或排错',
        zhTw: '開啟原 WebView 介面進行交叉比對或排錯',
        ja: '従来の WebView UI を開く',
        en: 'Open original WebView shell if needed',
        ko: '기존 WebView UI 열기',
      );
  String get unsavedChanges => tr(zhCn: '有未保存的更改', zhTw: '有未儲存的變更', ja: '未保存の変更があります', en: 'Unsaved changes', ko: '저장되지 않은 변경사항');
  String get discardChanges => tr(zhCn: '放弃', zhTw: '放棄', ja: '破棄', en: 'Discard', ko: '취소');
  String get saveSettings => tr(zhCn: '保存设置', zhTw: '儲存設定', ja: '保存', en: 'Save Settings', ko: '설정 저장');
  String get exportDone => tr(zhCn: '已保存备份到下载目录', zhTw: '已儲存備份到下載目錄', ja: 'ダウンロードに保存しました', en: 'Backup saved to Downloads', ko: '다운로드 폴더에 백업 저장됨');
  String get restoreDone => tr(zhCn: '数据库恢复成功', zhTw: '資料庫還原成功', ja: 'データベースを復元しました', en: 'Database restored', ko: 'DB 복원 완료');

  // Alias manager & collection fix-numbers
  String get aliasPrimaryHint => tr(zhCn: '主名称', zhTw: '主名稱', ja: 'メイン名', en: 'Primary name', ko: '대표 이름');
  String get aliasValuesHint => tr(zhCn: '别名（逗号分隔）', zhTw: '別名（逗號分隔）', ja: '別名（カンマ区切り）', en: 'Aliases (comma-separated)', ko: '별명 (쉼표 구분)');
  String get addAliasGroup => tr(zhCn: '新增别名组', zhTw: '新增別名組', ja: 'グループ追加', en: 'Add Group', ko: '그룹 추가');
  String get addSingleAlias => tr(zhCn: '添加别名', zhTw: '新增別名', ja: '別名を追加', en: 'Add Alias', ko: '별명 추가');
  String get aliasSearchOnline => tr(zhCn: '在线查别名', zhTw: '線上查別名', ja: 'オンライン検索', en: 'Search Online', ko: '온라인 검색');
  String get aliasEmptyList => tr(zhCn: '暂无别名记录', zhTw: '暫無別名記錄', ja: '別名データがありません', en: 'No alias groups yet', ko: '별명 그룹 없음');
  String get fixNumbersBtn => tr(zhCn: '扫描并修复异常番号', zhTw: '掃描並修復異常番號', ja: '品番異常を検出・修復', en: 'Scan & Fix Corrupted Numbers', ko: '비정상 품번 검사 및 복구');
  String fixNumbersPreviewTitle(int count) => tr(
        zhCn: '发现 $count 项可修复番号',
        zhTw: '發現 $count 項可修復番號',
        ja: '$count 件の修復候補が見つかりました',
        en: 'Found $count numbers to fix',
        ko: '$count개의 복구 대상 발견',
      );
  String fixNumbersApplied(int updated, int failed) => tr(
        zhCn: '已修复 $updated 项（失败 $failed 项）',
        zhTw: '已修復 $updated 項（失敗 $failed 項）',
        ja: '$updated 件を修復しました（失敗 $failed 件）',
        en: 'Fixed $updated items ($failed failed)',
        ko: '$updated건 복구 완료 (실패 $failed건)',
      );

  // Metatube & AI Backfill controls
  String get metatubeAllowLan => tr(zhCn: '允许局域网地址 (LAN)', zhTw: '允許區域網路位址 (LAN)', ja: 'LAN アドレスを許可', en: 'Allow LAN addresses', ko: 'LAN 주소 허용');
  String get metatubeConnect => tr(zhCn: '连接', zhTw: '連線', ja: '接続', en: 'Connect', ko: '연결');
  String get metatubeDisconnect => tr(zhCn: '断开', zhTw: '斷線', ja: '切断', en: 'Disconnect', ko: '연결 해제');
  String get metatubeRetest => tr(zhCn: '重新探测', zhTw: '重新探測', ja: '再テスト', en: 'Retest', ko: '다시 테스트');
  String metatubeConnectedCount(int count) => tr(
        zhCn: '已连接（$count 个源）',
        zhTw: '已連線（$count 個來源）',
        ja: '接続済み（$count ソース）',
        en: 'Connected ($count providers)',
        ko: '연결됨 ($count개 소스)',
      );
  String get metatubeDisconnected => tr(zhCn: '未连接', zhTw: '未連線', ja: '未接続', en: 'Disconnected', ko: '연결 안 됨');
  String get backfillStartBtn => tr(zhCn: '开始回填', zhTw: '開始回填', ja: 'バックフィル開始', en: 'Start Backfill', ko: '백필 시작');
  String get backfillStopBtn => tr(zhCn: '停止', zhTw: '停止', ja: '停止', en: 'Stop', ko: '중지');
  String get backfillRebuildBtn => tr(zhCn: '全部重建', zhTw: '全部重建', ja: 'すべて再構築', en: 'Rebuild All', ko: '전체 재구축');
  String get backfillRebuildConfirm => tr(
        zhCn: '确定清空已有结果并重新运行全库处理吗？',
        zhTw: '確定清空既有結果並重新執行全庫處理嗎？',
        ja: '既存データをクリアして全件再構築しますか？',
        en: 'Clear existing results and rebuild for the entire library?',
        ko: '기존 결과를 지우고 전체 라이브러리를 다시 처리할까요?',
      );
  String get backfillRefreshBtn => tr(zhCn: '刷新进度', zhTw: '重新整理進度', ja: '状態を更新', en: 'Refresh Status', ko: '상태 새로고침');
  String backfillRunningLabel(int done, int total) => tr(
        zhCn: '运行中：$done / $total',
        zhTw: '執行中：$done / $total',
        ja: '実行中：$done / $total',
        en: 'Running: $done / $total',
        ko: '진행 중: $done / $total',
      );
  String backfillPendingLabel(int pending) => tr(
        zhCn: '待处理：$pending 项',
        zhTw: '待處理：$pending 項',
        ja: '未処理：$pending 件',
        en: 'Pending: $pending',
        ko: '대기 중: $pending건',
      );

  // Collection health analysis & translation status
  String get analysisTotalVideos => tr(zhCn: '片库总影片数', zhTw: '片庫總影片數', ja: '総動画数', en: 'Total Videos', ko: '전체 동영상');
  String get analysisMissingNfo => tr(zhCn: '缺失 NFO 元数据', zhTw: '缺失 NFO 中繼資料', ja: 'NFO 未作成', en: 'Missing NFO', ko: 'NFO 누락');
  String get analysisCorruptedNumbers => tr(zhCn: '异常番号', zhTw: '異常番號', ja: '異常な品番', en: 'Corrupted Numbers', ko: '비정상 품번');
  String get analysisJapaneseTags => tr(zhCn: '含日文标签影片', zhTw: '含日文標籤影片', ja: '日本語タグあり', en: 'Videos with Japanese Tags', ko: '일본어 태그 포함');
  String get analysisEmptyActresses => tr(zhCn: '空女优列表', zhTw: '空女優列表', ja: '女優情報なし', en: 'Empty Actresses', ko: '배우 정보 없음');
  String get analysisEmptyTags => tr(zhCn: '空标签列表', zhTw: '空標籤列表', ja: 'タグなし', en: 'Empty Tags', ko: '태그 없음');
  String analysisMissingField(String field) => tr(
        zhCn: '缺失字段：$field',
        zhTw: '缺失欄位：$field',
        ja: '欠損フィールド：$field',
        en: 'Missing field: $field',
        ko: '누락 필드: $field',
      );
  String get alreadyTargetLanguage => tr(
        zhCn: '已是目标语言，无需翻译',
        zhTw: '已是目標語言，無需翻譯',
        ja: 'すでに対象言語のため翻訳不要です',
        en: 'Already in target language',
        ko: '이미 대상 언어입니다',
      );
  String get loadMoreResults => tr(
        zhCn: '加载更多结果',
        zhTw: '載入更多結果',
        ja: 'さらに読み込む',
        en: 'Load More Results',
        ko: '더 불러오기',
      );
  String scanSummary(int total, int inserted, int updated, int deleted) => tr(
        zhCn: '共 $total 部（新增 $inserted / 更新 $updated / 移除 $deleted）',
        zhTw: '共 $total 部（新增 $inserted / 更新 $updated / 移除 $deleted）',
        ja: '合計 $total 件（新規 $inserted / 更新 $updated / 削除 $deleted）',
        en: '$total videos (+$inserted / ~$updated / -$deleted)',
        ko: '총 $total편 (추가 $inserted / 갱신 $updated / 삭제 $deleted)',
      );

  // Batch tag source fetch / replace
  String get batchTagSourceTitle => tr(
        zhCn: '批量获取 / 更换视频标签',
        zhTw: '批次取得 / 更換影片標籤',
        ja: '動画タグの一括取得・切替',
        en: 'Batch Fetch / Replace Tags',
        ko: '동영상 태그 일괄 가져오기 / 교체',
      );
  String get batchTagSourceDesc => tr(
        zhCn: '从指定资料源批量获取并更新全库影片普通标签（保留自定义标签）',
        zhTw: '從指定資料來源批次取得並更新全庫影片一般標籤（保留自訂標籤）',
        ja: '指定ソースから全動画の通常タグを一括取得・置換（カスタムタグは保持）',
        en: 'Fetch or replace ordinary tags across the library from one source',
        ko: '지정한 소스에서 전체 라이브러리 일반 태그를 일괄 가져오기/교체',
      );
  String get batchTagSourceSelectHint => tr(
        zhCn: '选择用于获取视频标签的资料源，可先预览变更再正式写入 NFO 与数据库。',
        zhTw: '選擇用於取得影片標籤的資料來源，可先預覽變更再正式寫入 NFO 與資料庫。',
        ja: 'タグを取得するソースを選択してください。書き込み前のプレビューも可能です。',
        en: 'Choose a source to fetch video tags from. You can preview changes before writing.',
        ko: '태그를 가져올 소스를 선택하세요. 저장 전 변경 사항을 미리 볼 수 있습니다.',
      );
  String get batchTagSourcePreviewBtn => tr(
        zhCn: '预览变更',
        zhTw: '預覽變更',
        ja: '変更をプレビュー',
        en: 'Preview Changes',
        ko: '변경 미리보기',
      );
  String get batchTagSourceRunBtn => tr(
        zhCn: '开始批量获取',
        zhTw: '開始批次取得',
        ja: '一括取得を開始',
        en: 'Run Batch Update',
        ko: '일괄 업데이트 시작',
      );

  String metadataSummary(int filled, int failed, int skipped) => tr(
        zhCn: '已补全 $filled 项，失败 $failed 项，跳过 $skipped 项',
        zhTw: '已補全 $filled 項，失敗 $failed 項，略過 $skipped 項',
        ja: '補完 $filled 件、失敗 $failed 件、スキップ $skipped 件',
        en: '$filled filled, $failed failed, $skipped skipped',
        ko: '$filled개 채움, $failed개 실패, $skipped개 건너뜀',
      );

  // Task Center
  String get taskCenterTitle => tr(
        zhCn: '任务中心', zhTw: '任務中心', ja: 'タスクセンター',
        en: 'Task Center', ko: '작업 센터',
      );
  String get taskCenterTab => tr(
        zhCn: '任务', zhTw: '任務', ja: 'タスク', en: 'Tasks', ko: '작업',
      );
  String taskCenterNotificationCount(int count) => tr(
        zhCn: '$count 个任务正在进行',
        zhTw: '$count 個任務正在進行',
        ja: '$count 件のタスクが実行中',
        en: count == 1 ? '1 active task' : '$count active tasks',
        ko: '진행 중인 작업 $count개',
      );
  String get taskCenterCurrent => tr(
        zhCn: '当前任务', zhTw: '目前任務', ja: '進行中のタスク',
        en: 'Current tasks', ko: '진행 중인 작업',
      );
  String get taskCenterRecent => tr(
        zhCn: '最近任务', zhTw: '最近的任務', ja: '最近のタスク',
        en: 'Recent tasks', ko: '최근 작업',
      );
  String get taskCenterEmpty => tr(
        zhCn: '暂无当前或最近的任务',
        zhTw: '目前沒有進行中或最近的任務',
        ja: '進行中または最近のタスクはありません',
        en: 'No current or recent tasks',
        ko: '진행 중이거나 최근에 실행한 작업이 없습니다',
      );
  String get taskCenterScan => tr(
        zhCn: '片库扫描', zhTw: '片庫掃描', ja: 'ライブラリのスキャン',
        en: 'Library scan', ko: '라이브러리 스캔',
      );
  String get taskCenterBatchTag => tr(
        zhCn: '批量更新标签', zhTw: '批次更新標籤', ja: 'タグの一括更新',
        en: 'Batch tag update', ko: '태그 일괄 업데이트',
      );
  String get taskCenterBatchTagPreview => tr(
        zhCn: '批量标签预览', zhTw: '批次標籤預覽', ja: 'タグ一括更新のプレビュー',
        en: 'Batch tag preview', ko: '태그 일괄 업데이트 미리보기',
      );
  String get taskCenterSimilar => tr(
        zhCn: 'AI 相似推荐索引', zhTw: 'AI 相似推薦索引', ja: 'AI 類似作品のインデックス作成',
        en: 'AI similarity indexing', ko: 'AI 유사 작품 색인',
      );
  String get taskCenterFaces => tr(
        zhCn: 'AI 人脸回填', zhTw: 'AI 人臉回填', ja: 'AI 顔検出のバックフィル',
        en: 'AI face detection backfill', ko: 'AI 얼굴 감지 백필',
      );
  String get taskCenterAiTags => tr(
        zhCn: 'AI 标签回填', zhTw: 'AI 標籤回填', ja: 'AI タグのバックフィル',
        en: 'AI tag backfill', ko: 'AI 태그 백필',
      );
  String get taskCenterRunning => tr(
        zhCn: '运行中', zhTw: '執行中', ja: '実行中', en: 'Running', ko: '실행 중',
      );
  String get taskCenterCancelling => tr(
        zhCn: '正在取消', zhTw: '正在取消', ja: 'キャンセル中',
        en: 'Cancelling', ko: '취소 중',
      );
  String get taskCenterCompletedWithFailures => tr(
        zhCn: '已完成，部分失败', zhTw: '已完成，部分失敗', ja: '一部失敗して完了',
        en: 'Completed with failures', ko: '완료됨 (일부 실패)',
      );
  String get taskCenterCancelled => tr(
        zhCn: '已取消', zhTw: '已取消', ja: 'キャンセル済み',
        en: 'Cancelled', ko: '취소됨',
      );
  String get taskCenterStopped => tr(
        zhCn: '已停止', zhTw: '已停止', ja: '停止済み', en: 'Stopped', ko: '중지됨',
      );
  String get taskCenterInterrupted => tr(
        zhCn: '已中断', zhTw: '已中斷', ja: '中断', en: 'Interrupted', ko: '중단됨',
      );
  String taskCenterProcessed(int count) => tr(
        zhCn: '已处理 $count 项', zhTw: '已處理 $count 項',
        ja: '$count 件処理済み', en: '$count processed', ko: '$count건 처리됨',
      );
  String taskCenterProgress(int current, int total) => tr(
        zhCn: '已处理 $current / $total 项', zhTw: '已處理 $current / $total 項',
        ja: '$current / $total 件処理済み', en: '$current of $total processed',
        ko: '$total건 중 $current건 처리됨',
      );
  String get taskCenterProgressUnknown => tr(
        zhCn: '等待进度信息', zhTw: '等待進度資訊', ja: '進捗情報を待機中',
        en: 'Waiting for progress', ko: '진행 정보 대기 중',
      );
  String taskCenterFailureCount(int count) => tr(
        zhCn: '$count 项失败', zhTw: '$count 項失敗', ja: '$count 件失敗',
        en: count == 1 ? '1 item failed' : '$count items failed',
        ko: '$count건 실패',
      );
  String taskCenterWarningCount(int count) => tr(
        zhCn: '$count 条警告', zhTw: '$count 則警告', ja: '警告 $count 件',
        en: count == 1 ? '1 warning' : '$count warnings', ko: '경고 $count건',
      );
  String get taskCenterWarningExamples => tr(
        zhCn: '警告示例', zhTw: '警告範例', ja: '警告の例',
        en: 'Sample warnings', ko: '경고 예시',
      );
  String get taskCenterFailureExamples => tr(
        zhCn: '错误示例', zhTw: '錯誤範例', ja: 'エラーの例',
        en: 'Sample errors', ko: '오류 예시',
      );
  String get taskCenterDetails => tr(
        zhCn: '任务详情', zhTw: '任務詳情', ja: 'タスクの詳細',
        en: 'Task details', ko: '작업 상세',
      );
  String taskCenterSource(String source) => tr(
        zhCn: '来源：$source', zhTw: '來源：$source', ja: '取得元：$source',
        en: 'Source: $source', ko: '출처: $source',
      );
  String taskCenterStarted(String time) => tr(
        zhCn: '开始于 $time', zhTw: '開始於 $time', ja: '開始時刻：$time',
        en: 'Started at $time', ko: '시작: $time',
      );
  String taskCenterFinished(String time) => tr(
        zhCn: '结束于 $time', zhTw: '結束於 $time', ja: '終了時刻：$time',
        en: 'Finished at $time', ko: '종료: $time',
      );
  String get taskCenterActionFailed => tr(
        zhCn: '无法执行此操作', zhTw: '無法執行此操作', ja: '操作を実行できませんでした',
        en: 'Unable to complete the action', ko: '작업을 완료할 수 없습니다',
      );
  String taskCenterReason(String reason) => switch (reason) {
        'disabled' || 'not_enabled' => tr(
            zhCn: '此功能已禁用', zhTw: '此功能已停用', ja: 'この機能は無効です',
            en: 'This feature is disabled', ko: '이 기능은 꺼져 있습니다',
          ),
        'request_failed' || 'test_failed' => taskCenterActionFailed,
        'error' => taskFailed,
        'model_changed' => tr(
            zhCn: '服务模型已更改', zhTw: '服務模型已變更', ja: 'サービスのモデルが変更されました',
            en: 'The service model changed', ko: '서비스 모델이 변경되었습니다',
          ),
        'nothing_pending' || 'nothing_to_do' => tr(
            zhCn: '没有待处理项目', zhTw: '沒有待處理項目', ja: '処理待ちの項目はありません',
            en: 'No pending items', ko: '처리할 항목이 없습니다',
          ),
        'no_target' => tr(
            zhCn: '尚未设定目标模型', zhTw: '尚未設定目標模型', ja: '対象モデルが未設定です',
            en: 'The target model is not configured', ko: '대상 모델이 설정되지 않았습니다',
          ),
        'connection_changed' => tr(
            zhCn: '服务连接已更改', zhTw: '服務連線已變更', ja: 'サービスの接続設定が変更されました',
            en: 'The service connection changed', ko: '서비스 연결이 변경되었습니다',
          ),
        'auth' => tr(
            zhCn: '服务身份验证失败', zhTw: '服務驗證失敗', ja: 'サービスの認証に失敗しました',
            en: 'Service authentication failed', ko: '서비스 인증에 실패했습니다',
          ),
        'contract' => tr(
            zhCn: '服务响应与预期不符', zhTw: '服務回應不符預期', ja: 'サービスの応答形式が想定と異なります',
            en: 'The service returned an incompatible response', ko: '서비스 응답 형식이 호환되지 않습니다',
          ),
        'unreachable' => tr(
            zhCn: '无法连接服务', zhTw: '無法連線至服務', ja: 'サービスに接続できません',
            en: 'The service could not be reached', ko: '서비스에 연결할 수 없습니다',
          ),
        'not_configured' => tr(
            zhCn: '尚未配置服务', zhTw: '尚未設定服務', ja: 'サービスが設定されていません',
            en: 'The service is not configured', ko: '서비스가 설정되지 않았습니다',
          ),
        'model_unsupported' => tr(
            zhCn: '当前模型不支持此任务', zhTw: '目前的模型不支援此任務', ja: '現在のモデルはこのタスクに対応していません',
            en: 'The current model does not support this task', ko: '현재 모델이 이 작업을 지원하지 않습니다',
          ),
        'quota' => tr(
            zhCn: '服务用量已达上限', zhTw: '服務用量已達上限', ja: 'サービスの利用上限に達しました',
            en: 'The service usage limit was reached', ko: '서비스 사용 한도에 도달했습니다',
          ),
        'user' => tr(
            zhCn: '用户请求停止', zhTw: '使用者要求停止', ja: 'ユーザーが停止を要求しました',
            en: 'Stopped by request', ko: '사용자 요청으로 중지되었습니다',
          ),
        _ => tr(
            zhCn: '原因：$reason', zhTw: '原因：$reason', ja: '理由：$reason',
            en: 'Reason: $reason', ko: '이유: $reason',
          ),
      };
}
