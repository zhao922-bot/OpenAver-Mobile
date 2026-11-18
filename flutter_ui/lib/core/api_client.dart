import 'dart:async';
import 'dart:convert';
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

class SseEvent {
  const SseEvent(this.data);
  final Map<String, dynamic> data;

  String get type => (data['type'] as String?) ?? '';
}

class ApiClient {
  ApiClient({
    required int port,
    required this.token,
    HttpClientAdapter? httpClientAdapter,
  })  : _port = port,
        dio = Dio(
          BaseOptions(
            baseUrl: 'http://127.0.0.1:$port',
            connectTimeout: const Duration(seconds: 10),
            receiveTimeout: const Duration(minutes: 5),
            validateStatus: (status) => status != null && status < 500,
          ),
        ) {
    if (httpClientAdapter != null) {
      dio.httpClientAdapter = httpClientAdapter;
    }
    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          if (token.isNotEmpty) {
            options.headers['Authorization'] = 'Bearer $token';
          }
          handler.next(options);
        },
      ),
    );
  }

  final Dio dio;
  final int _port;
  final String token;

  String get baseUrl => 'http://127.0.0.1:$_port';
  Map<String, String> get authHeaders =>
      token.isEmpty ? const {} : {'Authorization': 'Bearer $token'};

  String resolveUrl(String pathOrUrl) {
    if (pathOrUrl.isEmpty) return '';
    if (pathOrUrl.startsWith('http://') || pathOrUrl.startsWith('https://')) {
      return pathOrUrl;
    }
    if (pathOrUrl.startsWith('/')) {
      return '$baseUrl$pathOrUrl';
    }
    return '$baseUrl/$pathOrUrl';
  }

  Future<Map<String, dynamic>> getJson(
    String path, {
    Map<String, dynamic>? queryParameters,
    CancelToken? cancelToken,
  }) async {
    final resp = await dio.get<dynamic>(
      path,
      queryParameters: queryParameters,
      cancelToken: cancelToken,
    );
    return _coerceMap(resp.data);
  }

  Future<List<dynamic>> getJsonList(
    String path, {
    Map<String, dynamic>? queryParameters,
  }) async {
    final resp = await dio.get<dynamic>(path, queryParameters: queryParameters);
    if (resp.data is List) return resp.data as List<dynamic>;
    return const [];
  }

  Future<Map<String, dynamic>> postJson(
    String path, {
    Object? data,
    Map<String, dynamic>? queryParameters,
    CancelToken? cancelToken,
  }) async {
    final resp = await dio.post<dynamic>(
      path,
      data: data,
      queryParameters: queryParameters,
      cancelToken: cancelToken,
    );
    return _coerceMap(resp.data);
  }

  Future<Map<String, dynamic>> putJson(
    String path, {
    Object? data,
  }) async {
    final resp = await dio.put<dynamic>(path, data: data);
    return _coerceMap(resp.data);
  }

  Future<Map<String, dynamic>> deleteJson(
    String path, {
    Map<String, dynamic>? queryParameters,
  }) async {
    final resp = await dio.delete<dynamic>(path, queryParameters: queryParameters);
    return _coerceMap(resp.data);
  }

  Stream<SseEvent> streamSse(
    String path, {
    String method = 'GET',
    Map<String, dynamic>? queryParameters,
    Object? data,
    CancelToken? cancelToken,
  }) async* {
    final response = await dio.request<ResponseBody>(
      path,
      data: data,
      queryParameters: queryParameters,
      cancelToken: cancelToken,
      options: Options(
        method: method,
        responseType: ResponseType.stream,
        headers: {'Accept': 'text/event-stream'},
        receiveTimeout: const Duration(hours: 2),
      ),
    );
    final body = response.data;
    if (body == null) return;

    final buffer = StringBuffer();
    var pendingEventType = '';
    await for (final chunk in utf8.decoder.bind(body.stream)) {
      buffer.write(chunk);
      var text = buffer.toString();
      var newlineIndex = text.indexOf('\n');
      while (newlineIndex != -1) {
        final line = text.substring(0, newlineIndex).trimRight();
        text = text.substring(newlineIndex + 1);
        if (line.isEmpty) {
          pendingEventType = '';
        } else if (line.startsWith('event:')) {
          pendingEventType = line.substring(6).trim();
        } else if (line.startsWith('data:')) {
          final payload = line.substring(5).trim();
          if (payload.isNotEmpty) {
            try {
              final decoded = jsonDecode(payload);
              if (decoded is Map<String, dynamic>) {
                if (pendingEventType.isNotEmpty && !decoded.containsKey('type')) {
                  decoded['type'] = pendingEventType;
                }
                yield SseEvent(decoded);
              }
            } catch (e) {
              debugPrint('SSE line JSON decode skipped: $e');
            }
          }
        }
        newlineIndex = text.indexOf('\n');
      }
      buffer
        ..clear()
        ..write(text);
    }
    final remaining = buffer.toString().trim();
    if (remaining.startsWith('data:')) {
      final payload = remaining.substring(5).trim();
      if (payload.isNotEmpty) {
        try {
          final decoded = jsonDecode(payload);
          if (decoded is Map<String, dynamic>) {
            if (pendingEventType.isNotEmpty && !decoded.containsKey('type')) {
              decoded['type'] = pendingEventType;
            }
            yield SseEvent(decoded);
          }
        } catch (e) {
          debugPrint('SSE trailing JSON decode skipped: $e');
        }
      }
    }
  }

  Map<String, dynamic> _coerceMap(dynamic data) {
    if (data is Map<String, dynamic>) return data;
    if (data is Map) return Map<String, dynamic>.from(data);
    if (data is String && data.isNotEmpty) {
      try {
        final decoded = jsonDecode(data);
        if (decoded is Map<String, dynamic>) return decoded;
      } catch (e) {
        debugPrint('JSON map coerce failed: $e');
      }
    }
    return const {};
  }
}
