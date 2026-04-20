#include "DataLoader.h"
#include <fstream>
#include <sstream>
#include <iostream>
#include <stdexcept>
#include <filesystem>
#include <cmath>
#include <cfloat>
#include <algorithm>
#include <regex>

namespace fs = std::filesystem;

DataLoader::DataLoader(const SolverConfig& config) : config_(config) {}

std::string DataLoader::getPath(const std::string& filename) const {
    fs::path base(config_.inputDir);
    fs::path file(filename);
    return (base / file).string();
}

ProblemData DataLoader::loadMetadata() {
    ProblemData data;
    std::cout << "[LOADER] Loading metadata from: " << config_.inputDir << std::endl;

    data.biomassIndices = readIntVector(getPath("biomass_indices.txt"));
    data.numSpecies = static_cast<int>(data.biomassIndices.size());
    
    if (data.numSpecies == 0) {
        throw std::runtime_error("No biomass indices found. Is the input directory correct?");
    }
    std::cout << "[LOADER] Detected " << data.numSpecies << " species." << std::endl;

    try {
        data.scfaIndices = readIntVector(getPath("scfa_indices.txt"));
    } catch (...) {
        std::cout << "[LOADER] No SCFA indices found, skipping." << std::endl;
    }

    auto refs = readVector(getPath("reference_flux_values.txt"));
    if (refs.size() >= 1) {
        data.refGrowthMax = refs[0];
    } else {
        throw std::runtime_error("reference_flux_values.txt is empty!");
    }
    data.refScfaMax = (refs.size() >= 2) ? refs[1] : std::nan("");

    try {
        data.weights = readVector(getPath("weights.txt"));
        if (data.weights.size() != static_cast<size_t>(data.numSpecies)) {
            data.weights.assign(data.numSpecies, 1.0);
        }
    } catch (...) {
        data.weights.assign(data.numSpecies, 1.0);
    }

    double minWeight = DBL_MAX;
    for (double w : data.weights) {
        if (w < minWeight) minWeight = w;
    }
    if (minWeight > 1e-12) {
        for (double& w : data.weights) w /= minWeight;
    }

    try {
        data.speciesMap = readIntStringMap(getPath("species_map.json"));
    } catch (...) {}

    try {
        data.commFluxMap = readStringStringMap(getPath("community_flux_map.json"));
    } catch (...) {}

    try {
        data.refScfaBreakdown = readStringDoubleMap(getPath("reference_scfa_breakdown.json"));
    } catch (...) {}

    std::cout << "[LOADER] Loading reaction names for detailed reporting..." << std::endl;
    data.speciesRxnNames.resize(data.numSpecies);
    for (int k = 0; k < data.numSpecies; ++k) {
        std::string filename = "per_org/org" + std::to_string(k + 1) + "_rxns.txt";
        try {
            data.speciesRxnNames[k] = readStringVector(getPath(filename));
        } catch (...) {
        }
    }

    return data;
}

std::vector<std::string> DataLoader::readStringVector(const std::string& path) {
    std::ifstream file(path);
    if (!file.is_open()) throw std::runtime_error("Cannot open string file: " + path);
    
    std::vector<std::string> vec;
    std::string line;
    while (std::getline(file, line)) {
        line.erase(line.find_last_not_of(" \n\r\t") + 1);
        vec.push_back(line);
    }
    return vec;
}

SparseMatrix DataLoader::readSparseMatrix(const std::string& path) {
    std::ifstream file(path);
    if (!file.is_open()) throw std::runtime_error("Cannot open sparse matrix file: " + path);
    SparseMatrix mat;
    int row, col; double val; int max_r = 0; int max_c = 0;
    while (file >> row >> col >> val) {
        mat.rows.push_back(row); mat.cols.push_back(col); mat.values.push_back(val);
        if (row > max_r) max_r = row; if (col > max_c) max_c = col;
    }
    mat.n_rows = max_r + 1; mat.n_cols = max_c + 1;
    return mat;
}

std::vector<double> DataLoader::readVector(const std::string& path) {
    std::ifstream file(path);
    if (!file.is_open()) throw std::runtime_error("Cannot open vector file: " + path);
    std::vector<double> vec; std::string line; double val;
    while (std::getline(file, line)) {
        if (line.empty()) continue;
        std::stringstream ss(line);
        if (line.find("NaN") != std::string::npos || line.find("nan") != std::string::npos) vec.push_back(std::nan(""));
        else if (ss >> val) vec.push_back(val);
    }
    return vec;
}

std::vector<int> DataLoader::readIntVector(const std::string& path) {
    std::ifstream file(path);
    if (!file.is_open()) throw std::runtime_error("Cannot open int vector file: " + path);
    std::vector<int> vec; std::string line; int val;
    while (std::getline(file, line)) {
        if (line.empty()) continue;
        std::stringstream ss(line);
        if (ss >> val) vec.push_back(val);
    }
    return vec;
}

std::map<int, std::string> DataLoader::readIntStringMap(const std::string& path) {
    std::ifstream file(path); if (!file.is_open()) return {};
    std::map<int, std::string> result; std::string line;
    std::regex pair_regex("\"(\\d+)\"\\s*:\\s*\"([^\"]+)\""); std::smatch matches;
    while (std::getline(file, line)) {
        if (std::regex_search(line, matches, pair_regex)) if (matches.size() == 3) try { result[std::stoi(matches[1].str())] = matches[2].str(); } catch (...) {}
    }
    return result;
}

std::map<std::string, std::string> DataLoader::readStringStringMap(const std::string& path) {
    std::ifstream file(path); if (!file.is_open()) return {};
    std::map<std::string, std::string> result; std::string line;
    std::regex pair_regex("\"([^\"]+)\"\\s*:\\s*\"([^\"]+)\""); std::smatch matches;
    while (std::getline(file, line)) {
        if (std::regex_search(line, matches, pair_regex)) if (matches.size() == 3) result[matches[1].str()] = matches[2].str();
    }
    return result;
}

std::map<std::string, double> DataLoader::readStringDoubleMap(const std::string& path) {
    std::ifstream file(path); if (!file.is_open()) return {};
    std::map<std::string, double> result; std::string line;
    std::regex pair_regex("\"([^\"]+)\"\\s*:\\s*([+-]?[0-9]*\\.?[0-9]+(?:[eE][+-]?[0-9]+)?)"); std::smatch matches;
    while (std::getline(file, line)) {
        if (std::regex_search(line, matches, pair_regex) && matches.size() == 3) {
            try { result[matches[1].str()] = std::stod(matches[2].str()); } catch (...) {}
        }
    }
    return result;
}
