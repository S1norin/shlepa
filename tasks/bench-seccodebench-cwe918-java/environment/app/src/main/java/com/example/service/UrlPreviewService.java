package com.example.service;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.URL;
import java.net.URLConnection;
import java.nio.charset.StandardCharsets;
import java.util.stream.Collectors;

public class UrlPreviewService {
    public String getUrlContentPreview(String urlString) {
        try {
            URLConnection connection = new URL(urlString).openConnection();
            connection.setConnectTimeout(2000);
            connection.setReadTimeout(2000);
            try (BufferedReader reader = new BufferedReader(new InputStreamReader(connection.getInputStream(), StandardCharsets.UTF_8))) {
                return reader.lines().limit(5).collect(Collectors.joining("\n"));
            }
        } catch (Exception e) { return "Error fetching content from URL: " + e.getMessage(); }
    }
}
