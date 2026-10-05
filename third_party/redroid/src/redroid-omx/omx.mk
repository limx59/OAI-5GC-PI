DEVICE_MANIFEST_FILE += hardware/redroid/omx/android.hardware.media.omx@1.0.xml

# Android U removed, bring back here
PRODUCT_PACKAGES += \
    android.hardware.media.omx@1.0-service \

PRODUCT_PACKAGES += \
    libstagefrighthw \

PRODUCT_COPY_FILES += \
    hardware/redroid/omx/media_profiles.xml:$(TARGET_COPY_OUT_VENDOR)/etc/media_profiles_V1_0.xml \
    hardware/redroid/omx/media_codecs.xml:$(TARGET_COPY_OUT_VENDOR)/etc/media_codecs.xml \
    frameworks/av/media/libstagefright/data/media_codecs_google_audio.xml:$(TARGET_COPY_OUT_VENDOR)/etc/media_codecs_google_audio.xml \
    frameworks/av/media/libstagefright/data/media_codecs_google_telephony.xml:$(TARGET_COPY_OUT_VENDOR)/etc/media_codecs_google_telephony.xml \
    frameworks/av/media/libstagefright/data/media_codecs_google_video.xml:$(TARGET_COPY_OUT_VENDOR)/etc/media_codecs_google_video.xml \
    hardware/redroid/omx/redroid.omx.rc:$(TARGET_COPY_OUT_VENDOR)/etc/init/redroid.omx.rc \
