package com.noetl.utils;

import org.junit.Test;

import static org.junit.Assert.*;

public class DateTimeUtilTest {

  @Test
  public void testCanParseYMD() throws Exception {
    assertEquals(true, DateTimeUtil.canParseYMD("2015.1.1"));
    assertEquals(true, DateTimeUtil.canParseYMD("2015.11.30"));
    assertEquals(false, DateTimeUtil.canParseYMD("2015.11.a3"));
  }
}
