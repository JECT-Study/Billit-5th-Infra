package com.ject.tripsheet

import org.springframework.boot.autoconfigure.SpringBootApplication
import org.springframework.boot.runApplication

@SpringBootApplication
class TripsheetApplication

fun main(args: Array<String>) {
    runApplication<TripsheetApplication>(*args)
}
