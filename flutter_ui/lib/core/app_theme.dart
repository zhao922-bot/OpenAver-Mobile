import 'package:flutter/material.dart';

enum AppThemeMode {
  light('light'),
  dim('dim'),
  dark('dark');

  const AppThemeMode(this.id);
  final String id;

  static AppThemeMode fromString(String? raw) {
    return switch (raw) {
      'light' => AppThemeMode.light,
      'dark' => AppThemeMode.dark,
      _ => AppThemeMode.dim,
    };
  }
}

@immutable
class OpenAverPalette extends ThemeExtension<OpenAverPalette> {
  const OpenAverPalette({
    required this.canvas,
    required this.surface,
    required this.surfaceHigh,
    required this.stroke,
    required this.textPrimary,
    required this.textSecondary,
    required this.textMuted,
    required this.accent,
    required this.blue,
    required this.success,
    required this.warning,
    required this.danger,
    required this.favoritePink,
    required this.brightness,
  });

  final Color canvas;
  final Color surface;
  final Color surfaceHigh;
  final Color stroke;
  final Color textPrimary;
  final Color textSecondary;
  final Color textMuted;
  final Color accent;
  final Color blue;
  final Color success;
  final Color warning;
  final Color danger;
  final Color favoritePink;
  final Brightness brightness;

  static const OpenAverPalette dimPalette = OpenAverPalette(
    canvas: Color(0xFF111317),
    surface: Color(0xFF1A1D24),
    surfaceHigh: Color(0xFF232832),
    stroke: Color(0x1FFFFFFF),
    textPrimary: Color(0xFFF3F4F6),
    textSecondary: Color(0xFFB4BCC9),
    textMuted: Color(0xFF8892A2),
    accent: Color(0xFFFF8A4C),
    blue: Color(0xFF60A5FA),
    success: Color(0xFF34D399),
    warning: Color(0xFFFF9F0A),
    danger: Color(0xFFFF453A),
    favoritePink: Color(0xFFFF4D6D),
    brightness: Brightness.dark,
  );

  static const OpenAverPalette darkPalette = OpenAverPalette(
    canvas: Color(0xFF090B0E),
    surface: Color(0xFF12151B),
    surfaceHigh: Color(0xFF1C212B),
    stroke: Color(0x1CFFFFFF),
    textPrimary: Color(0xFFF3F4F6),
    textSecondary: Color(0xFFB4BCC9),
    textMuted: Color(0xFF818B9C),
    accent: Color(0xFFFF8A4C),
    blue: Color(0xFF60A5FA),
    success: Color(0xFF30D158),
    warning: Color(0xFFFF9F0A),
    danger: Color(0xFFFF453A),
    favoritePink: Color(0xFFFF4D6D),
    brightness: Brightness.dark,
  );

  static const OpenAverPalette lightPalette = OpenAverPalette(
    canvas: Color(0xFFF5F6F8),
    surface: Color(0xFFFFFFFF),
    surfaceHigh: Color(0xFFECEFF3),
    stroke: Color(0x1F181B20),
    textPrimary: Color(0xFF181B20),
    textSecondary: Color(0xFF4D5562),
    textMuted: Color(0xFF747D8C),
    accent: Color(0xFFD14E12),
    blue: Color(0xFF007AFF),
    success: Color(0xFF22A958),
    warning: Color(0xFFD97706),
    danger: Color(0xFFDC2626),
    favoritePink: Color(0xFFFF4D6D),
    brightness: Brightness.light,
  );

  static OpenAverPalette of(BuildContext context) {
    return Theme.of(context).extension<OpenAverPalette>() ?? dimPalette;
  }

  @override
  OpenAverPalette copyWith({
    Color? canvas,
    Color? surface,
    Color? surfaceHigh,
    Color? stroke,
    Color? textPrimary,
    Color? textSecondary,
    Color? textMuted,
    Color? accent,
    Color? blue,
    Color? success,
    Color? warning,
    Color? danger,
    Color? favoritePink,
    Brightness? brightness,
  }) {
    return OpenAverPalette(
      canvas: canvas ?? this.canvas,
      surface: surface ?? this.surface,
      surfaceHigh: surfaceHigh ?? this.surfaceHigh,
      stroke: stroke ?? this.stroke,
      textPrimary: textPrimary ?? this.textPrimary,
      textSecondary: textSecondary ?? this.textSecondary,
      textMuted: textMuted ?? this.textMuted,
      accent: accent ?? this.accent,
      blue: blue ?? this.blue,
      success: success ?? this.success,
      warning: warning ?? this.warning,
      danger: danger ?? this.danger,
      favoritePink: favoritePink ?? this.favoritePink,
      brightness: brightness ?? this.brightness,
    );
  }

  @override
  OpenAverPalette lerp(ThemeExtension<OpenAverPalette>? other, double t) {
    if (other is! OpenAverPalette) return this;
    return OpenAverPalette(
      canvas: Color.lerp(canvas, other.canvas, t)!,
      surface: Color.lerp(surface, other.surface, t)!,
      surfaceHigh: Color.lerp(surfaceHigh, other.surfaceHigh, t)!,
      stroke: Color.lerp(stroke, other.stroke, t)!,
      textPrimary: Color.lerp(textPrimary, other.textPrimary, t)!,
      textSecondary: Color.lerp(textSecondary, other.textSecondary, t)!,
      textMuted: Color.lerp(textMuted, other.textMuted, t)!,
      accent: Color.lerp(accent, other.accent, t)!,
      blue: Color.lerp(blue, other.blue, t)!,
      success: Color.lerp(success, other.success, t)!,
      warning: Color.lerp(warning, other.warning, t)!,
      danger: Color.lerp(danger, other.danger, t)!,
      favoritePink: Color.lerp(favoritePink, other.favoritePink, t)!,
      brightness: t < 0.5 ? brightness : other.brightness,
    );
  }
}

ThemeData buildOpenAverTheme(AppThemeMode mode) {
  final palette = switch (mode) {
    AppThemeMode.light => OpenAverPalette.lightPalette,
    AppThemeMode.dark => OpenAverPalette.darkPalette,
    AppThemeMode.dim => OpenAverPalette.dimPalette,
  };
  final isDark = palette.brightness == Brightness.dark;
  final scheme = ColorScheme(
    brightness: palette.brightness,
    primary: palette.accent,
    onPrimary: isDark ? const Color(0xFF1B0D04) : Colors.white,
    secondary: palette.blue,
    onSecondary: Colors.white,
    error: palette.danger,
    onError: Colors.white,
    surface: palette.surface,
    onSurface: palette.textPrimary,
  );

  return ThemeData(
    useMaterial3: true,
    brightness: palette.brightness,
    colorScheme: scheme,
    scaffoldBackgroundColor: palette.canvas,
    cardColor: palette.surface,
    dividerColor: palette.stroke,
    appBarTheme: AppBarTheme(
      backgroundColor: palette.surface,
      foregroundColor: palette.textPrimary,
      elevation: 0,
      scrolledUnderElevation: 0,
      surfaceTintColor: Colors.transparent,
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: palette.surface,
      indicatorColor: palette.accent.withValues(alpha: 0.16),
      surfaceTintColor: Colors.transparent,
      labelTextStyle: WidgetStateProperty.resolveWith((states) {
        final selected = states.contains(WidgetState.selected);
        return TextStyle(
          fontSize: 11,
          fontWeight: selected ? FontWeight.w600 : FontWeight.w500,
          color: selected ? palette.accent : palette.textMuted,
        );
      }),
      iconTheme: WidgetStateProperty.resolveWith((states) {
        final selected = states.contains(WidgetState.selected);
        return IconThemeData(
          size: 22,
          color: selected ? palette.accent : palette.textMuted,
        );
      }),
    ),
    chipTheme: ChipThemeData(
      backgroundColor: palette.surfaceHigh,
      selectedColor: palette.accent.withValues(alpha: 0.18),
      side: BorderSide(color: palette.stroke),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      labelStyle: TextStyle(color: palette.textSecondary, fontSize: 12),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: palette.surfaceHigh,
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: BorderSide(color: palette.stroke),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: BorderSide(color: palette.stroke),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: BorderSide(color: palette.accent, width: 1.5),
      ),
      hintStyle: TextStyle(color: palette.textMuted, fontSize: 13),
    ),
    extensions: [palette],
  );
}
