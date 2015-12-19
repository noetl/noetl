package com.noetl.utils;

import java.text.ParseException;
import java.text.SimpleDateFormat;
import java.util.Calendar;
import java.util.Date;

public class DateTimeUtil {

  public static String getCurrentTimeDefault() {
    return Calendar.getInstance().getTime().toString();
  }

  public static String getCurrentTimeYMDHMS() {
    SimpleDateFormat yyyyMMdd_hHmmss = new SimpleDateFormat("yyyyMMdd_HHmmss");
    return yyyyMMdd_hHmmss.format(Calendar.getInstance().getTime());
  }

  public static String getCurrentTimeYMD() {
    SimpleDateFormat yyyyMMdd = new SimpleDateFormat("yyyy.MM.dd");
    return yyyyMMdd.format(Calendar.getInstance().getTime());
  }

  public static boolean canParseYMD(String dateString) {
    SimpleDateFormat yyyyMMdd = new SimpleDateFormat("yyyy.MM.dd");
    try {
      Date parsed = yyyyMMdd.parse(dateString);
    } catch (ParseException e) {
      return false;
    }
    return true;
  }

  public static void main(String[] args) {
    System.out.println(getCurrentTimeDefault());
    System.out.println(getCurrentTimeYMDHMS());
  }
}
