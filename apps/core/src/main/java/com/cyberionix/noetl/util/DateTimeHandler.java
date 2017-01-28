package com.cyberionix.noetl.util;

import java.text.ParseException;
import java.util.regex.Pattern;

import org.joda.time.LocalDate;
import org.joda.time.DateTime;
import org.joda.time.format.DateTimeFormat;
import org.joda.time.format.DateTimeFormatter;
import org.joda.time.Days;

/**
 * Created by Nodar Momtselidze.
 */
public class DateTimeHandler {


    static final String dateOutDefaultString = "0001-01-01";

    static final String dateDefaultPattern = "yyyy-MM-dd";

    static final DateTimeFormatter defaultDateFormat = DateTimeFormat.forPattern(dateDefaultPattern); // ddf is a default date format

    static final Pattern PATTERN = Pattern.compile("^(-?0|-?[1-9]\\d*)(\\.\\d+)?(E\\d+)?$");

    /**
     * changeDateFormat convert given string date format to format(yyyy-MM-dd)
     *
     * @param dateInString
     * @param formatter
     * @return String
     */
    public static String changeDateFormat(String dateInString, String formatter) throws ParseException {
        String dateOutString = dateOutDefaultString;										//dateInString;
        DateTimeFormatter dateformatIn = DateTimeFormat.forPattern(formatter);
        DateTimeFormatter dateformatOut = DateTimeFormat.forPattern(dateDefaultPattern);
        if (!dateformatIn.equals(dateformatOut)){
            try {
                DateTime date = dateformatIn.parseDateTime(dateInString);
                dateOutString=date.toString(dateDefaultPattern) ;
            } catch (Exception e ){
                System.out.println("Not correct format: " + formatter + " for " + dateInString);
            }
        }
        return dateOutString;
    }
    /**
     * assuming the default date format is YYYY-MM-DD returns LocalDate or 0001-01-01 if converting failed
     *
     * @param dateInString
     * @return LocalDate
     */
    public static LocalDate setLocDate(String dateInString)   throws ParseException  {
        LocalDate parsedDate;
        try {
            if (dateInString.matches("\\d{4}-\\d{2}-\\d{2}")) {
                parsedDate = defaultDateFormat.parseDateTime(dateInString).toLocalDate();
            } else {
                throw new ParseException("", 0);
            }
        } catch (ParseException ex) {
            parsedDate = defaultDateFormat.parseDateTime(dateOutDefaultString).toLocalDate();		//"0001-01-01"
        }
        return parsedDate;
    } //  setLocDate

    /**
     * @param dateInString
     * @param dateInFormat
     * @return LocalDate
     */
    public static LocalDate setLocDate(String dateInString, String dateInFormat)   throws ParseException  {
        String date = dateInString;
        if(!dateInFormat.equals(dateDefaultPattern)){
            date = changeDateFormat(dateInString, dateInFormat);
        }
        return	setLocDate(date);
    } //  setLocDate

    /**
     * @param locDate
     * @return String LocalDate
     */
    public static String getLocDate(LocalDate locDate)  {
        return locDate.toString(dateDefaultPattern);
    } //  getLocDate
    /**
     * @param locDate
     * @param dateFormat
     * @return String LocalDate
     */
    public static String getLocDate(LocalDate locDate,String dateFormat )  {
        return locDate.toString(dateFormat);
    } //  getLocDate
    //=======================================================================================
    public static String dateFormat(String dateInString, String dateOutFormat)   throws ParseException  {
        LocalDate parsedDate;
        parsedDate = defaultDateFormat.parseDateTime(dateInString).toLocalDate();
        return	getLocDate(parsedDate,dateOutFormat);
    } //  dateFormat
    /**
     * @param dateInString
     * @param dateInFormat
     * @param dateOutFormat
     * @return String dateFormat
     */
    public static String dateFormat(String dateInString, String dateInFormat, String dateOutFormat)   throws ParseException  {
//			String date = dateInString;
        LocalDate parsedDate;
        if(!dateInFormat.equals(dateDefaultPattern)){
//				  DateTimeFormatter dateformatIn = org.joda.time.format.DateTimeFormat.forPattern(dateInFormat);
            parsedDate = setLocDate(dateInString,dateInFormat);
        } else {
            parsedDate = setLocDate(dateInString);
        }
        return	getLocDate(parsedDate,dateOutFormat);
    } //  dateFormat
//=========================================================================================
    /**
     * @param locDate
     * @param addDays
     * @return LocalDate as String
     */
    public static String addDays(LocalDate locDate,int addDays )  {
        return "" + locDate.plusDays(addDays);
    } //  getLocDate
    /**
     * @param locDate
     * @param addWeeks
     * @return LocalDate as String
     */
    public static String addWeeks(LocalDate locDate,int addWeeks )  {
        return "" + locDate.plusWeeks(addWeeks);
    } //  getLocDate
    /**
     * @param locDate
     * @param addMonth
     * @return LocalDate as String
     */
    public static String addMonths(LocalDate locDate,int addMonth )  {
        return "" + locDate.plusMonths(addMonth);
    } //  getLocDate

    /**
     * @param locDate
     * @param addmonth
     * @return LocalDate as String
     */
    public static LocalDate getAddMonths(LocalDate locDate,int addmonth )  {
        return  locDate.plusMonths(addmonth);
    } //  getLocDate

    /**
     * @param locDate
     * @param dateFormat
     * @return LocalDate as String
     */
    public static String getMonthFirstLocDate(LocalDate locDate,String dateFormat)  {
        return locDate.dayOfMonth().withMinimumValue().toString(dateFormat);
    } //  getFirstLocDate

    /**
     * @param fromDateString
     * @param toDateString
     * @return LocalDate as String
     */
    public static int getDaysDiff(String fromDateString,String toDateString)  {
        LocalDate past;
        int days = 0;
        try {
            past = setLocDate(fromDateString);
            LocalDate today = setLocDate(toDateString);
            days = Days.daysBetween(past, today).getDays();
        } catch (ParseException e) {
            days = 0;
        }
        return days;
    } //  getDaysDiff


    /**
     * @param locDate
     * @return LocalDate as String
     */
    public static String getMonthFirstLocDate(LocalDate locDate)  {
        return locDate.dayOfMonth().withMinimumValue().toString(dateDefaultPattern);
    } //  getFirstLocDate
    /**
     * @param locDate
     * @param dateFormat
     * @return LocalDate as String
     */
    public static String getMonthLastLocDate(LocalDate locDate,String dateFormat)  {
        return locDate.dayOfMonth().withMaximumValue().toString(dateFormat);
    } //  getLastLocDate

    /**
     * @param locDate
     * @return String Last day of the month
     */
    public static String getMonthLastLocDate(LocalDate locDate)  {
        return locDate.dayOfMonth().withMaximumValue().toString(dateDefaultPattern);
    } //  getLastLocDate

    /**
     * @param locDate
     * @return int Last day of the month
     */
    public static int getMonthLastDay(String locDate)  {
        try {
            return setLocDate(locDate).dayOfMonth().getMaximumValue();
        } catch (ParseException e) {
            return 31;
        }
    } //  getLastLocDate

    /**
     * @param locDate
     * @return int dd
     */
    public static int getMonthDay(String locDate)  {
        try {
            return setLocDate(locDate).dayOfMonth().get();
        } catch (ParseException e) {
            return 31;
        }
    } //  getLastLocDate

    /**
     * @param locDate
     * @return String "YYYY"
     */
    public static String getYear(LocalDate locDate)  {
        return "" + locDate.getYear();
    } //  getYear

    /**
     * @param dateInString
     * @return int YYYY
     */
    public static int year(String dateInString) throws ParseException {
        LocalDate ld = setLocDate(dateInString);
        return ld.getYear();
    } //  getYear

    /**
     * @param locDate
     * @return String  MM
     */
    public static String getMonthOfYear(LocalDate locDate)  {
        return "" + locDate.getMonthOfYear();
    } //  getMonthOfYear

    /**
     * gets month from date as int
     *
     * @param dateInString
     * @return int MM
     */
    public static int month(String dateInString) throws ParseException {
        LocalDate ld = setLocDate(dateInString);
        return ld.getMonthOfYear();
    }

    /**
     * gets yearmonth from date as int
     *
     * @param dateInString
     * @return int YYYYMM
     */
    public static int yrmon(String dateInString) throws ParseException {
        return year(dateInString) * 100 + month(dateInString);
    }

    /**
     * gets yearmonth from date as int
     *
     * @param dateInString
     * @return int YYYYMM
     */
    public static String yearmon(String dateInString) throws ParseException {
        return "" + year(dateInString) * 100 + month(dateInString);
    }

    /**
     * adds month number to yearmonth
     *
     * @param date
     * @param mon
     *            months to add
     * @return int YYYYMM
     */
    public static int yrmon(String date, int mon) {
        int addmon, yyear;
        try {
            addmon = month(date) + mon - 1;
            yyear = year(date);
        } catch (ParseException e) {
            return (int) 000101;
        }
        return (int) ((yyear + addmon / 12) * 100 + addmon % 12) + 1;
    }

    /**
     * adds month number to yearmonth
     *
     * @param date
     * @param mon
     *            months to add
     * @return String "YYYYMM"
     */
    public static String yearmon(String date, int mon) {
        int addmon, yyear;
        try {
            addmon = month(date) + mon - 1;
            yyear = year(date);
        } catch (ParseException e) {
            return "000101";
        }
        return "" + (((yyear + addmon / 12) * 100 + addmon % 12) + 1);
    }

    /**
     * difference months
     *
     * @param date1
     * @param date2
     * @return int months
     */
    public static int yrmon(String date1, String date2) {
        try {
            return (year(date1) * 12 + month(date1) - year(date2) * 12 - month(date2));
        } catch (ParseException e) {
            return 0;
        }
    }

    /**
     * difference months
     *
     * @param date1
     * @param date2
     * @return String months
     */
    public static String yearmon(String date1, String date2) {
        try {
            return "" + (year(date1) * 12 + month(date1) - year(date2) * 12 - month(date2));
        } catch (ParseException e) {
            return "0";
        }
    }
    /**
     * @param locDate
     * @return String Day of Month
     */
    public static String getDateOfMonth(LocalDate locDate)  {
        return "" + locDate.getDayOfMonth();
    } //  getDayOfMonth

    /**
     * @param locDate
     * @return String Day of Year
     */
    public static String getDayOfYear(LocalDate locDate)  {
        return "" + locDate.getDayOfYear();
    } //  getDayOfYear

    /**
     * @param locDate
     * @return String Day of Week (1~7)
     */
    public static String getDayOfWeek(LocalDate locDate)  {
        return "" + locDate.getDayOfWeek();
    } //  getDayOfWeek

    /**
     * @param locDate
     * @return Integer Day of Week (1~7)
     */
    public static Integer getDayOfMonth(LocalDate locDate)  {
        return locDate.getDayOfMonth() ;
    } //  getDayOfMonth

    /**
     * @param locDate
     * @return String Day of Week (1~7)
     */
    public static String getWeekOfWeekyear(LocalDate locDate)  {
        return "" + locDate.getWeekOfWeekyear();
    } //  getDayOfWeek

    /**
     * @param locDate
     * @return String First Date of the Month
     */
    public static String getWeekFirstLocDate(LocalDate locDate)  {
        return locDate.dayOfWeek().withMinimumValue().toString(dateDefaultPattern);
    } //  getLastLocDate
    /**
     * @param locDate
     * @return String as last Date of the Month
     */
    public static String getWeekLastLocDate(LocalDate locDate)  {
        return locDate.dayOfWeek().withMaximumValue().toString(dateDefaultPattern);
    } //  getLastLocDate
    /**
     * @param locDate
     * @return String Quarter of Year
     */
    public static String getQuartOfYear(LocalDate locDate)  {
        return "" + (int)Math.floor(locDate.getMonthOfYear()/4 + 1);
    } //  getQuartOfYear

    /**
     * @param locDate
     * @return String Week of Year
     */
    public static String getWeekOfYear(LocalDate locDate)  {
        return "" + locDate.getWeekOfWeekyear();
    } //  getWeekOfYear
/*
		public static String addDays(LocalDate locDate, int days)  {
			return "" + locDate.getWeekOfWeekyear();
		} //  getWeekOfYear
*/
    /**
     * Test df module
     */
    public static void main(String[] args) throws ParseException {
        System.out.println("======Input date as String: 2015-04-02 =========== ");
        String dtn = "2015-02-02";
        LocalDate pdtn = setLocDate(dtn);
        System.out.println("Formated Date1: \t" + dateFormat(dtn,"yyyy/MM/dd/w e EEEE"));
        System.out.println("Formated Date2: \t" + dateFormat("15/04/02","YY/MM/dd","YYYYMMe EEEE"));
        System.out.println("Return difference in days Date2: \t" + getDaysDiff("2015-04-02","2015-04-02"));
        System.out.println("Return difference in days Date2: \t" + (0*2.35d));
        System.out.println("Local Date: \t" 	+ pdtn);
        System.out.println("Formated Date: \t" + getLocDate(pdtn,"yyyy-MM"));
        System.out.println("Get First Date: " + getMonthFirstLocDate(pdtn));
        System.out.println("Get Last Date:  " + getMonthLastLocDate(pdtn));

        System.out.println("Get Last Day of the Month:  " + getMonthLastDay(dtn));
        System.out.println("Get Day of the Month:  " + getMonthDay(dtn));

        System.out.println("Year: \t\t" 		+ getYear(pdtn));
        System.out.println("Quart of Year: \t" + getQuartOfYear(pdtn));
        System.out.println("Month of Year: \t" + getMonthOfYear(pdtn));
        System.out.println("Week of Year: \t" 	+ getWeekOfYear(pdtn));
        System.out.println("First Date of Week: \t" + getWeekFirstLocDate(pdtn));
        System.out.println("Last Date of Week: \t" + getWeekLastLocDate(pdtn));
        System.out.println("Day of Year: \t" 	+ getDayOfYear(pdtn));
        System.out.println("Date of Month: \t" + getDateOfMonth(pdtn));
        System.out.println("Day of Week: \t" 	+ getDayOfWeek(pdtn));
        System.out.println("Week of Weekyear: \t" + getWeekOfWeekyear(pdtn));
        System.out.println("Minus 25 Days: \t" + addDays(pdtn,-25));
        System.out.println("Add 4 Month: \t" 	+ addMonths(pdtn,4));
        System.out.println("Minus 4 Month: \t" + addMonths(pdtn,-4));
//		============================================================
        System.out.println("======Input date as String: 20150321 =========== ");
        String dtp = "20150321";
        LocalDate pdtp = setLocDate(dtp,"yyyyMMdd");
        System.out.println("Formated Date1: \t" + dateFormat(dtp,"YYYYMMdd","yyyyMMdd/w e EEEE"));
        System.out.println("Formated Date2: \t" + dateFormat("15/04/02","YY/MM/dd","YYYYMMe EEEE"));
        System.out.println("Local Date: \t" 	+ pdtp);
        System.out.println("Formated Date: \t" + getLocDate(pdtp,"yyyy-MM"));
        System.out.println("Get First Date: " + getMonthFirstLocDate(pdtp));
        System.out.println("Get Last Date:  " + getMonthLastLocDate(pdtp));
        System.out.println("Year: \t\t" 		+ getYear(pdtp));
        System.out.println("Quart of Year: \t" + getQuartOfYear(pdtp));
        System.out.println("Month of Year: \t" + getMonthOfYear(pdtp));
        System.out.println("Week of Year: \t" 	+ getWeekOfYear(pdtp));
        System.out.println("First Date of Week: \t" + getWeekFirstLocDate(pdtp));
        System.out.println("Last Date of Week: \t" + getWeekLastLocDate(pdtp));
        System.out.println("Day of Year: \t" 	+ getDayOfYear(pdtp));
        System.out.println("Date of Month: \t" + getDateOfMonth(pdtp));
        System.out.println("Day of Week: \t" 	+ getDayOfWeek(pdtp));
        System.out.println("Week of Weekyear: \t" + getWeekOfWeekyear(pdtp));
        System.out.println("Add 25 Days: \t" 	+ addDays(pdtp,25));
        System.out.println("Minus 25 Days: \t" + addDays(pdtp,-25));
        System.out.println("Add 4 Month: \t" 	+ addMonths(pdtp,4));
        System.out.println("Minus 4 Month: \t" + addMonths(pdtp,-4));
//			============================================================
        System.out.println("======Input date ERROR as String: 201503-21 =========== ");
        String dte = "201503-21";
        LocalDate pdte = setLocDate(dte);
        System.out.println("Local Date: \t" 	+ pdte);
        System.out.println("Formated Date: \t" + getLocDate(pdte,"MM-dd-yyyy"));
        System.out.println("Year: \t\t" 		+ getYear(pdte));
        System.out.println("yrmon: \t\t" 		+ yrmon(dte));
        System.out.println("Quart of Year: \t" + getQuartOfYear(pdte));
        System.out.println("Month of Year: \t" + getMonthOfYear(pdte));
        System.out.println("Week of Year: \t" 	+ getWeekOfYear(pdte));
        System.out.println("Day of Year: \t" 	+ getDayOfYear(pdte));
        System.out.println("Date of Month: \t" + getDateOfMonth(pdte));
        System.out.println("Day of Week: \t" 	+ getDayOfWeek(pdte));
    }



}
