#pragma once
#include "Config.h"
#include <vector>
#include <string>
#include <map>

class DataLoader {
public:
    explicit DataLoader(const SolverConfig& config);
    
    ProblemData loadMetadata();
    
    static SparseMatrix readSparseMatrix(const std::string& path);
    
    static std::vector<double> readVector(const std::string& path);
    static std::vector<int> readIntVector(const std::string& path);
    
    static std::vector<std::string> readStringVector(const std::string& path);
    
    static std::map<int, std::string> readIntStringMap(const std::string& path);
    static std::map<std::string, std::string> readStringStringMap(const std::string& path);
    static std::map<std::string, double> readStringDoubleMap(const std::string& path);

private:
    SolverConfig config_;
    std::string getPath(const std::string& filename) const;
};
