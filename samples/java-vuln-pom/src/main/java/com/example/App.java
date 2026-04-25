package com.example;

import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;

public class App {
    private static final Logger LOGGER = LogManager.getLogger(App.class);

    public static void main(String[] args) {
        LOGGER.info("Hello from intentionally vulnerable Maven demo project.");
        System.out.println("Done.");
    }
}
