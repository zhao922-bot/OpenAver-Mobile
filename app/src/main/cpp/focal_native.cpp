#include <android/log.h>
#include <jni.h>
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

#define LOG_TAG "OpenAverFocal"
#define ALOGW(...) __android_log_print(ANDROID_LOG_WARN, LOG_TAG, __VA_ARGS__)

namespace {

struct Face { int row; int col; int scale; float q; };

struct Cascade {
    std::vector<int8_t> codes;
    std::vector<float> preds;
    std::vector<float> thresholds;
    int depth = 0;
    int trees = 0;
};

const int32_t QCOS[] = {
    256, 251, 236, 212, 181, 142, 97, 49, 0, -49, -97, -142, -181, -212, -236, -251,
    -256, -251, -236, -212, -181, -142, -97, -49, 0, 49, 97, 142, 181, 212, 236, 251
};
const int32_t QSIN[] = {
    0, 49, 97, 142, 181, 212, 236, 251, 256, 251, 236, 212, 181, 142, 97, 49,
    0, -49, -97, -142, -181, -212, -236, -251, -256, -251, -236, -212, -181, -142, -97, -49
};

bool read_u32(std::ifstream &in, uint32_t &out) {
    in.read(reinterpret_cast<char*>(&out), sizeof(out));
    return in.good();
}


float classify_region(const Cascade &c, int r0, int col0, int scale,
                      const std::vector<uint8_t> &pixels, int dim) {
    int r = r0 << 8;
    int col = col0 << 8;
    float out = 0.0f;
    int root = 0;
    for (int i = 0; i < c.trees; ++i) {
        int idx = 1;
        for (int d = 0; d < c.depth; ++d) {
            int b = root + 4 * idx;
            int x1 = (((r + c.codes[b] * scale) >> 8) * dim) +
                     ((col + c.codes[b + 1] * scale) >> 8);
            int x2 = (((r + c.codes[b + 2] * scale) >> 8) * dim) +
                     ((col + c.codes[b + 3] * scale) >> 8);
            idx = (idx << 1) + (pixels[x1] <= pixels[x2] ? 1 : 0);
        }
        out += c.preds[(1 << c.depth) * i + idx - (1 << c.depth)];
        if (out <= c.thresholds[i]) return -1.0f;
        root += 4 * (1 << c.depth);
    }
    return out - c.thresholds[c.trees - 1];
}

std::vector<Face> run_cascade(const Cascade &c, const std::vector<uint8_t> &pixels,
                              int rows, int cols, int min_size, int max_size) {
    std::vector<Face> dets;
    const float shift = 0.10f;
    const float scale_factor = 1.08f;
    int scale = min_size;
    while (scale <= max_size) {
        int step = static_cast<int>(shift * scale);
        if (step < 1) step = 1;
        int offset = scale / 2 + 1;
        for (int row = offset; row <= rows - offset; row += step) {
            for (int col = offset; col <= cols - offset; col += step) {
                float q = classify_region(c, row, col, scale, pixels, cols);
                if (q > 0.0f) dets.push_back({row, col, scale, q});
            }
        }
        int grow = static_cast<int>(scale * scale_factor - scale);
        scale += grow > 2 ? grow : 2;
    }
    return dets;
}

struct Cluster { float x; float y; float weight; };

std::vector<Cluster> strongest_cluster(const std::vector<Face> &faces,
                                       int width, int height, int axis) {
    int n = static_cast<int>(faces.size());
    std::vector<int> parent(n);
    for (int i = 0; i < n; ++i) parent[i] = i;
    auto find = [&](int x) {
        while (parent[x] != x) {
            parent[x] = parent[parent[x]];
            x = parent[x];
        }
        return x;
    };
    for (int i = 0; i < n; ++i) {
        for (int j = i + 1; j < n; ++j) {
            float pi = axis == 0 ? float(faces[i].col) / width : float(faces[i].row) / height;
            float pj = axis == 0 ? float(faces[j].col) / width : float(faces[j].row) / height;
            if (std::fabs(pi - pj) <= 0.05f) {
                int a = find(i), b = find(j);
                if (a != b) parent[b] = a;
            }
        }
    }
    std::vector<Cluster> groups;
    std::vector<int> roots;
    for (int i = 0; i < n; ++i) {
        int root = find(i);
        auto it = std::find(roots.begin(), roots.end(), root);
        if (it == roots.end()) {
            roots.push_back(root);
            groups.push_back({0.0f, 0.0f, 0.0f});
        }
        Cluster &g = groups[std::find(roots.begin(), roots.end(), root) - roots.begin()];
        float w = float(faces[i].scale) * faces[i].q;
        g.x += (float(faces[i].col) / width) * w;
        g.y += (float(faces[i].row) / height) * w;
        g.weight += w;
    }
    std::sort(groups.begin(), groups.end(), [](const Cluster &a, const Cluster &b) {
        return a.weight > b.weight;
    });
    if (!groups.empty() && groups.front().weight > 0.0f) {
        groups.front().x /= groups.front().weight;
        groups.front().y /= groups.front().weight;
    }
    return groups;
}

void rgb_to_gray(const uint8_t *rgb, int count, std::vector<uint8_t> &gray) {
    gray.resize(count);
    const float k = 257.0f / 256.0f;
    for (int i = 0, o = 0; i < count; ++i, o += 3) {
        gray[i] = static_cast<uint8_t>((0.299f * rgb[o] + 0.587f * rgb[o + 1] +
                                        0.114f * rgb[o + 2]) * k);
    }
}

bool unpack_cascade(Cascade &c, const std::string &path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) return false;
    in.seekg(8);
    uint32_t depth = 0, trees = 0;
    if (!read_u32(in, depth) || !read_u32(in, trees)) return false;
    int n_code = 4 * (1 << depth) - 4;
    int n_leaf = 1 << depth;
    c.depth = static_cast<int>(depth);
    c.trees = static_cast<int>(trees);
    c.codes.reserve((4 + n_code) * trees);
    c.preds.reserve(n_leaf * trees);
    c.thresholds.reserve(trees);
    for (uint32_t t = 0; t < trees; ++t) {
        int8_t zeros[4] = {0, 0, 0, 0};
        c.codes.insert(c.codes.end(), zeros, zeros + 4);
        std::vector<int8_t> code(n_code);
        in.read(reinterpret_cast<char*>(code.data()), n_code);
        if (!in) return false;
        c.codes.insert(c.codes.end(), code.begin(), code.end());
        std::vector<float> pred(n_leaf);
        in.read(reinterpret_cast<char*>(pred.data()), sizeof(float) * n_leaf);
        if (!in) return false;
        c.preds.insert(c.preds.end(), pred.begin(), pred.end());
        float threshold = 0.0f;
        in.read(reinterpret_cast<char*>(&threshold), sizeof(threshold));
        if (!in) return false;
        c.thresholds.push_back(threshold);
    }
    return true;
}

std::string cascade_path(JNIEnv *env, jobject context) {
    jclass cls = env->GetObjectClass(context);
    jmethodID get_files = env->GetMethodID(cls, "getFilesDir", "()Ljava/io/File;");
    jobject file = env->CallObjectMethod(context, get_files);
    jclass file_cls = env->GetObjectClass(file);
    jmethodID get_abs = env->GetMethodID(file_cls, "getAbsolutePath", "()Ljava/lang/String;");
    jstring jpath = static_cast<jstring>(env->CallObjectMethod(file, get_abs));
    const char *chars = env->GetStringUTFChars(jpath, nullptr);
    std::string base(chars);
    env->ReleaseStringUTFChars(jpath, chars);
    return base + "/openaver_data/lib/core/focal/facefinder";
}

} // namespace

extern "C" JNIEXPORT jint JNICALL
Java_dev_openaver_mobile_MainActivity_openaverFocalDetect(
        JNIEnv *env, jobject /* this */, jbyteArray jrgb, jint width, jint height,
        jint min_face, jobject context, jfloatArray jout) {
    try {
        static Cascade cascade;
        static bool loaded = false;
        if (!loaded) {
            if (!unpack_cascade(cascade, cascade_path(env, context))) {
                ALOGW("unable to unpack facefinder");
                return 0;
            }
            loaded = true;
        }

        const int count = width * height;
        std::vector<uint8_t> gray(count);
        {
            jbyte *p = env->GetByteArrayElements(jrgb, nullptr);
            rgb_to_gray(reinterpret_cast<const uint8_t*>(p), count, gray);
            env->ReleaseByteArrayElements(jrgb, p, JNI_ABORT);
        }

        int max_face = static_cast<int>(float(width) * 0.8f);
        std::vector<Face> faces = run_cascade(cascade, gray, height, width,
                                              min_face, max_face);
        if (faces.empty()) return 0;

        int axis = (int(float(height) * 0.71f) < width) ? 0 : 1;
        std::vector<Cluster> clusters = strongest_cluster(faces, width, height, axis);
        if (clusters.empty() || clusters.front().weight <= 0.0f) return 0;
        float out[2] = {clusters.front().x, clusters.front().y};
        env->SetFloatArrayRegion(jout, 0, 2, out);
        return 1;
    } catch (...) {
        ALOGW("native focal detection failed");
        return 0;
    }
}

extern "C" JNIEXPORT jstring JNICALL
Java_dev_openaver_mobile_MainActivity_nativeAbi(JNIEnv *env, jobject /* this */) {
#if defined(__aarch64__)
    return env->NewStringUTF("arm64-v8a");
#elif defined(__x86_64__)
    return env->NewStringUTF("x86_64");
#elif defined(__arm__)
    return env->NewStringUTF("armeabi-v7a");
#elif defined(__i386__)
    return env->NewStringUTF("x86");
#else
    return env->NewStringUTF("unknown");
#endif
}



