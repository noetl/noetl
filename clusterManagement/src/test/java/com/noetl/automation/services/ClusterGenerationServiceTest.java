package com.noetl.automation.services;

import org.junit.Test;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class ClusterGenerationServiceTest {

  @Test
  public void testMonitor() throws Exception {
    ClusterGenerationService service = new ClusterGenerationService(null, null, new EmptyNotificationService(), null);
    HashMap<String, List<String>> fileMappings = new HashMap<>();
    fileMappings.put("account", new ArrayList<String>() {{
      add("account_201509.csv");
      add("account_201508.csv");
    }});
    fileMappings.put("data", new ArrayList<String>() {{
      add("data_201508.csv");
    }});
    ArrayList<String> filesForCluster = new ArrayList<>();
    assertTrue(service.monitor(fileMappings, filesForCluster));
    ArrayList<String> expected = new ArrayList<String>() {{
      add("account_201508.csv");
      add("data_201508.csv");
    }};
    assertTrue(expected.containsAll(filesForCluster) && filesForCluster.containsAll(expected));
  }

  @Test
  public void testMonitor1() throws Exception {
    ClusterGenerationService service = new ClusterGenerationService(null, null, new EmptyNotificationService(), null);
    HashMap<String, List<String>> fileMappings = new HashMap<>();
    fileMappings.put("account", new ArrayList<String>() {{
      add("account_201509.csv");
      add("account_201508.csv");
    }});
    fileMappings.put("data", new ArrayList<String>() {{
      add("data_201508.csv");
    }});
    fileMappings.put("customer", new ArrayList<String>());
    ArrayList<String> filesForCluster = new ArrayList<>();
    assertFalse(service.monitor(fileMappings, filesForCluster));
    ArrayList<String> expected = new ArrayList<>();
    assertTrue(expected.containsAll(filesForCluster) && filesForCluster.containsAll(expected));
  }

  @Test
  public void testMonitor2() throws Exception {
    ClusterGenerationService service = new ClusterGenerationService(null, null, new EmptyNotificationService(), null);
    HashMap<String, List<String>> fileMappings = new HashMap<>();
    fileMappings.put("account", new ArrayList<String>() {{
      add("account_201509.csv");
      add("account_201508.csv");
    }});
    fileMappings.put("data", new ArrayList<String>() {{
      add("data_201508.csv");
      add("data_201509.csv");
    }});
    ArrayList<String> filesForCluster = new ArrayList<>();
    assertTrue(service.monitor(fileMappings, filesForCluster));
    ArrayList<String> expected = new ArrayList<String>() {{
      add("account_201508.csv");
      add("account_201509.csv");
      add("data_201508.csv");
      add("data_201509.csv");
    }};
    assertTrue(expected.containsAll(filesForCluster) && filesForCluster.containsAll(expected));
  }

  @Test
  public void testMonitor3() throws Exception {
    ClusterGenerationService service = new ClusterGenerationService(null, null, new EmptyNotificationService(), null);
    HashMap<String, List<String>> fileMappings = new HashMap<>();
    fileMappings.put("account", new ArrayList<String>() {{
    }});
    ArrayList<String> filesForCluster = new ArrayList<>();
    assertFalse(service.monitor(fileMappings, filesForCluster));
    ArrayList<String> expected = new ArrayList<>();
    assertTrue(expected.containsAll(filesForCluster) && filesForCluster.containsAll(expected));
  }

  @Test
  public void testMonitor4() throws Exception {
    ClusterGenerationService service = new ClusterGenerationService(null, null, new EmptyNotificationService(), null);
    HashMap<String, List<String>> fileMappings = new HashMap<>();
    ArrayList<String> filesForCluster = new ArrayList<>();
    assertFalse(service.monitor(fileMappings, filesForCluster));
    ArrayList<String> expected = new ArrayList<>();
    assertTrue(expected.containsAll(filesForCluster) && filesForCluster.containsAll(expected));
  }
}
