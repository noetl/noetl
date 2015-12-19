package com.noetl.aws.utils;

import com.noetl.utils.DateTimeUtil;

public class AWSS3Util {

  private final static String ERROR = "Invalid s3 path format in configuration. ";

  public static String getBucketName(String path) {
    path = path.trim();
    s3PathSanityCheck(path);

    int start = path.indexOf("//");
    String fromBucketName = path.substring(start + 2);
    int nextSlash = fromBucketName.indexOf("/");
    if (nextSlash <= 0)
      throw new RuntimeException(ERROR + "Cannot parse the bucket name from your path: " + path);
    return fromBucketName.substring(0, nextSlash);
  }

  public static String getKey(String path) {
    path = path.trim();
    s3PathSanityCheck(path);

    int start = path.indexOf("//");
    String fromBucketName = path.substring(start + 2);
    int bucketNameEnd = fromBucketName.indexOf("/");
    if (bucketNameEnd <= 0)
      throw new RuntimeException(ERROR + "Cannot parse the bucket name from your path: " + path);

    String key = fromBucketName.substring(bucketNameEnd + 1);
    if (key.trim().equals(""))
      return "";
    if (!key.endsWith("/"))
      throw new RuntimeException(ERROR + "Key should end with '/': " + path);
    return key;
  }

  public static String makeS3Path(String bucketName, String key) {
    return String.format("s3://%s/%s", bucketName, key);
  }

  public static String appendTimeToKey(String path) {
    path = path.trim();
    s3PathSanityCheck(path);

    return path + DateTimeUtil.getCurrentTimeYMDHMS() + "/";
  }

  private static void s3PathSanityCheck(String path) {
    if (!(path.startsWith("s3://") || path.startsWith("s3n://")))
      throw new RuntimeException(ERROR + "Path doesn't start with s3:// or s3n://: " + path);
    if (!path.endsWith("/"))
      throw new RuntimeException(ERROR + "The s3 path in configuration must end with '/': " + path);
    if (path.endsWith("//"))
      throw new RuntimeException(ERROR + "It ends with more than one '/' or it doesn't specify bucket name: " + path);
  }
}
