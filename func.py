import math, osmnx as ox


def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def getNearestNodeId(G, lat, lon):
    return ox.distance.nearest_nodes(G, X=lon, Y=lat)

def getFare(modePathList, mode="walk", discount=False):
    '''
    Jeep fare computation based on LTFRB Fare Matrix for PUJs dated Oct. 8 2023
    Tricycle fare based on Angeles City TODA Fare Matrix (Ordinance No. 723, S-2024)
    '''
    baseJeepFare = 13.0
    perKmFareIncrease = 1.8
    totalDist = 0

    if mode == "walk":
        return 0.0
    
    for u, v in zip(modePathList, modePathList[1:]):
        totalDist += haversine(u[1], u[0], v[1], v[0])
    totalDist = totalDist / 1000

    if mode == "jeep":
        if totalDist < 5:
            if discount:
                return round(baseJeepFare * 0.8 * 4) / 4
            return baseJeepFare
        else:
            fare = baseJeepFare + (perKmFareIncrease * (math.floor(totalDist) - 4))
            if discount:
                return round(fare * 0.8 * 4) / 4
            return round(fare * 4) / 4
    elif mode == "trike":
        if totalDist < 1.1:
            if discount:
                return 35 * 0.8
            return 35.0
        else:
            increments = int(totalDist - 0.1)
            fare = 35.0 + max(0, increments) * 15
            if discount:
                return fare * 0.8
            return fare