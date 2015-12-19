package com.noetl.aws.utils;

import com.noetl.aws.utils.AWSS3Util;
import org.junit.Test;

import static org.junit.Assert.assertEquals;

public class AWSS3UtilTest {

  @Test
  public void testGetBucketName() throws Exception {
    assertEquals("noetl-company-auto", AWSS3Util.getBucketName("s3://noetl-company-auto/fresh/"));
    assertEquals("noetl-company-auto", AWSS3Util.getBucketName("s3://noetl-company-auto/"));
  }

  @Test
  public void testGetBucketKeyName() throws Exception {
    assertEquals("fresh/", AWSS3Util.getKey("s3://noetl-company-auto/fresh/"));
    assertEquals("", AWSS3Util.getKey("s3://noetl-company-auto/ "));
  }
}
