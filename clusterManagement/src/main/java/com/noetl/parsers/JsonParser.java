package com.noetl.parsers;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.MapperFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.commons.io.FileUtils;
import org.apache.commons.io.IOUtils;


import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.util.HashMap;
import java.util.Map;

public class JsonParser {
  private JsonParser() {
  }

  public static ObjectMapper getMapper() {
    ObjectMapper mapper = new ObjectMapper();
    mapper.configure(MapperFeature.ACCEPT_CASE_INSENSITIVE_PROPERTIES, true);
    return mapper;
  }

  public static <T> T toObject(InputStream in, Class<T> objClass, int excludeFirstN, int excludeLastN) throws IOException {
    File file = jsonStringToFile(in, excludeFirstN, excludeLastN);
    return getMapper().readValue(file, objClass);
  }

  public static Map<String, ?> toMap(InputStream in) throws IOException {
    return toMap(in, 0, 0);
  }

  public static Map<String, ?> toMap(File in) throws IOException {
    TypeReference<HashMap<?, ?>> typeRef = new TypeReference<HashMap<?, ?>>() {
    };
    return getMapper().readValue(in, typeRef);
  }

  public static Map<String, ?> toMap(InputStream in, int excludeFirstN, int excludeLastN) throws IOException {
    File file = jsonStringToFile(in, excludeFirstN, excludeLastN);
    return toMap(file);
  }

  private static File jsonStringToFile(InputStream in, int excludeFirstN, int excludeLastN) throws IOException {
    if (excludeFirstN < 0)
      throw new IllegalArgumentException("Expect excludeFirstN to be >=0");
    if (excludeLastN < 0)
      throw new IllegalArgumentException("Expect excludeLastN to be >=0");

    String JsonStr = IOUtils.toString(in);
    JsonStr = JsonStr.substring(excludeFirstN, JsonStr.length() - excludeLastN);

    File file = File.createTempFile("fileForJson", "");
    file.deleteOnExit();
    FileUtils.writeStringToFile(file, JsonStr);
    return file;
  }
}
