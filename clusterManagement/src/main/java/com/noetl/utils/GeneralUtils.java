package com.noetl.utils;

import java.io.PrintWriter;
import java.io.StringWriter;

public class GeneralUtils {
  public static String getStackTrace(Exception e) {
    StringWriter sw = new StringWriter();
    PrintWriter pw = new PrintWriter(sw);
    e.printStackTrace(pw);
    return sw.toString();
  }
}
