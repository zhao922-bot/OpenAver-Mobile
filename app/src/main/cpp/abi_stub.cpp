#include <jni.h>

extern "C" JNIEXPORT jstring JNICALL
Java_dev_openaver_mobile_MainActivity_nativeAbi(
        JNIEnv *env,
        jobject /* this */) {
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
