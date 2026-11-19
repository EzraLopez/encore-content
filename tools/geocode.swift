// Prints "id<TAB>latitude<TAB>longitude" for each "id<TAB>query" line on
// stdin, using Apple's geocoder (no key, no permission). Used by
// tools/add_coordinates.py; a query that finds nothing prints "id<TAB>-".
import CoreLocation
import Foundation

let geocoder = CLGeocoder()
while let line = readLine() {
    let parts = line.split(separator: "\t", maxSplits: 1).map(String.init)
    guard parts.count == 2 else { continue }
    let done = DispatchSemaphore(value: 0)
    var out = "\(parts[0])\t-"
    geocoder.geocodeAddressString(parts[1]) { places, _ in
        if let c = places?.first?.location?.coordinate {
            out = String(format: "%@\t%.5f\t%.5f", parts[0], c.latitude, c.longitude)
        }
        done.signal()
    }
    while done.wait(timeout: .now() + 0.05) == .timedOut {
        RunLoop.current.run(until: Date().addingTimeInterval(0.05))
    }
    print(out)
    fflush(stdout)
    // Apple's geocoder throttles bursts.
    Thread.sleep(forTimeInterval: 3.0)
}
