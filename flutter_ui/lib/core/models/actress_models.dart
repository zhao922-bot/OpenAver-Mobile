import 'package:flutter/painting.dart';

class ActressProfile {
  const ActressProfile({
    required this.name,
    required this.aliases,
    required this.birth,
    required this.age,
    required this.height,
    required this.cup,
    required this.bust,
    required this.waist,
    required this.hip,
    required this.hometown,
    required this.hobby,
    required this.photoUrl,
    required this.photoSource,
    required this.autoFocal,
    required this.cropMode,
    required this.isFavorite,
    required this.videoCount,
  });

  final String name;
  final List<String> aliases;
  final String birth;
  final int? age;
  final String height;
  final String cup;
  final String bust;
  final String waist;
  final String hip;
  final String hometown;
  final String hobby;
  final String photoUrl;
  final String photoSource;
  final String autoFocal;
  final String cropMode;
  final bool isFavorite;
  final int videoCount;

  Alignment get focalAlignment {
    if (cropMode == 'default' || autoFocal.isEmpty) {
      return Alignment.center;
    }
    final parts = autoFocal.split(',');
    if (parts.length != 2) return Alignment.center;
    final x = double.tryParse(parts[0].trim());
    final y = double.tryParse(parts[1].trim());
    if (x == null || y == null) return Alignment.center;
    return Alignment(
      (x.clamp(0.0, 1.0) * 2.0) - 1.0,
      (y.clamp(0.0, 1.0) * 2.0) - 1.0,
    );
  }

  String get measurementsText {
    final parts = [
      if (bust.isNotEmpty) 'B:$bust',
      if (waist.isNotEmpty) 'W:$waist',
      if (hip.isNotEmpty) 'H:$hip',
    ];
    return parts.join(' / ');
  }

  ActressProfile copyWith({
    String? name,
    List<String>? aliases,
    String? birth,
    int? age,
    String? height,
    String? cup,
    String? bust,
    String? waist,
    String? hip,
    String? hometown,
    String? hobby,
    String? photoUrl,
    String? photoSource,
    String? autoFocal,
    String? cropMode,
    bool? isFavorite,
    int? videoCount,
  }) {
    return ActressProfile(
      name: name ?? this.name,
      aliases: aliases ?? this.aliases,
      birth: birth ?? this.birth,
      age: age ?? this.age,
      height: height ?? this.height,
      cup: cup ?? this.cup,
      bust: bust ?? this.bust,
      waist: waist ?? this.waist,
      hip: hip ?? this.hip,
      hometown: hometown ?? this.hometown,
      hobby: hobby ?? this.hobby,
      photoUrl: photoUrl ?? this.photoUrl,
      photoSource: photoSource ?? this.photoSource,
      autoFocal: autoFocal ?? this.autoFocal,
      cropMode: cropMode ?? this.cropMode,
      isFavorite: isFavorite ?? this.isFavorite,
      videoCount: videoCount ?? this.videoCount,
    );
  }

  factory ActressProfile.fromJson(Map<String, dynamic> json, {int fallbackVideoCount = 0}) {
    final rawAliases = (json['aliases'] as List?) ?? const [];
    final rawName = ((json['name'] ?? json['primary_name']) as String?) ?? '';
    return ActressProfile(
      name: rawName,
      aliases: rawAliases.map((e) => e.toString().trim()).where((e) => e.isNotEmpty).toList(),
      birth: (json['birth'] as String?) ?? '',
      age: (json['age'] as num?)?.toInt(),
      height: (json['height']?.toString() ?? '').replaceAll('null', ''),
      cup: (json['cup'] as String?) ?? '',
      bust: (json['bust']?.toString() ?? '').replaceAll('null', ''),
      waist: (json['waist']?.toString() ?? '').replaceAll('null', ''),
      hip: (json['hip']?.toString() ?? '').replaceAll('null', ''),
      hometown: (json['hometown'] as String?) ?? '',
      hobby: (json['hobby'] as String?) ?? '',
      photoUrl: (json['photo_url'] as String?) ?? '',
      photoSource: (json['photo_source'] as String?) ?? '',
      autoFocal: (json['auto_focal'] as String?) ?? '',
      cropMode: (json['crop_mode'] as String?) ?? 'auto',
      isFavorite: json['is_favorite'] == true || json.containsKey('photo_source'),
      videoCount: (json['video_count'] as num?)?.toInt() ?? fallbackVideoCount,
    );
  }
}

class PhotoCandidate {
  const PhotoCandidate({
    required this.id,
    required this.source,
    required this.thumbUrl,
    required this.fullUrl,
    this.videoPath,
  });

  final String id;
  final String source;
  final String thumbUrl;
  final String fullUrl;
  final String? videoPath;

  factory PhotoCandidate.fromJson(Map<String, dynamic> json) {
    return PhotoCandidate(
      id: (json['id'] as String?) ?? '',
      source: (json['source'] as String?) ?? '',
      thumbUrl: (json['thumb_url'] as String?) ?? '',
      fullUrl: (json['full_url'] as String?) ?? '',
      videoPath: json['video_path'] as String?,
    );
  }
}
